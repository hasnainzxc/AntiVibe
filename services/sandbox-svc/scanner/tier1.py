"""Tier 1 orchestrator — chains clone→detect→ast→parallel analyzers→merge."""

import asyncio
import time
import json
from pathlib import Path
from typing import Optional
import structlog

from scanner.clone import clone_repo, RepoTooLarge, CloneError
from scanner.detect_stack import detect_stack, UnsupportedStackError
from scanner.ast_parser import parse_repo, ParseResult
from scanner.secret_detector import scan_directory, SecretFinding as DetectorSecretFinding
from scanner.config_flaws import analyze_config_flaws, ConfigFlawFinding
from scanner.llm_extractor import analyze_code, LLMClient, LLMExtractResult, LLMFinding

logger = structlog.get_logger(__name__)

TIER1_TIMEOUT = 60  # circuit-breaker seconds


async def run_tier1(
    repo_url: str,
    branch: str = "HEAD",
    llm_client: Optional[LLMClient] = None,
) -> dict:
    """Run Tier 1 pipeline and return merged results.

    Args:
        repo_url: GitHub repo URL
        branch: Branch to clone
        llm_client: Optional LLM client (uses default if None)

    Returns dict with keys:
        status: "complete" | "partial" | "error"
        repo: cloned local path
        stack: detected stack name
        findings: list of merged finding dicts
        duration_ms: wallclock ms
        error: error message (if status=="error")
    """
    start_time = time.time()
    result = {
        "status": "complete",
        "repo": "",
        "stack": "",
        "findings": [],
        "duration_ms": 0,
        "error": None,
    }

    repo_path = ""
    stack = ""

    try:
        logger.info("tier1.clone.start", repo=repo_url)
        repo_path = clone_repo(repo_url, branch=branch)
        result["repo"] = repo_path
        logger.info("tier1.clone.done", path=repo_path)

    except RepoTooLarge as e:
        logger.error("tier1.clone.too_large", repo=repo_url)
        result["status"] = "error"
        result["error"] = str(e)
        result["duration_ms"] = int((time.time() - start_time) * 1000)
        return result
    except CloneError as e:
        logger.error("tier1.clone.failed", repo=repo_url, error=str(e))
        result["status"] = "error"
        result["error"] = str(e)
        result["duration_ms"] = int((time.time() - start_time) * 1000)
        return result

    try:
        logger.info("tier1.detect_stack.start")
        stack = detect_stack(repo_path)
        result["stack"] = stack.value
        logger.info("tier1.detect_stack.done", stack=stack.value)

    except UnsupportedStackError as e:
        logger.error("tier1.unsupported_stack", error=str(e))
        result["status"] = "error"
        result["error"] = str(e)
        result["duration_ms"] = int((time.time() - start_time) * 1000)
        return result

    # AST parse must complete before parallel analyzers
    logger.info("tier1.ast.start")
    ast_result: ParseResult = parse_repo(repo_path, stack.value)
    logger.info("tier1.ast.done", routes=len(ast_result.routes), env_refs=len(ast_result.env_refs))

    # Circuit-breaker: abort if >60s walltime
    elapsed = time.time() - start_time
    if elapsed > TIER1_TIMEOUT:
        logger.warning("tier1.circuit_breaker", elapsed=elapsed)
        result["status"] = "partial"
        result["duration_ms"] = int(elapsed * 1000)
        return result

    logger.info("tier1.analyze.start")
    remaining = max(TIER1_TIMEOUT - elapsed, 5)

    try:
        tasks = await asyncio.gather(
            _run_secret_detector(repo_path, remaining),
            _run_config_flaws(repo_path, stack.value, remaining),
            _run_llm_extractor(ast_result, llm_client, remaining),
            return_exceptions=True,
        )
    except TimeoutError:
        logger.error("tier1.analyzers_timeout")
        result["status"] = "partial"
        result["duration_ms"] = int((time.time() - start_time) * 1000)
        return result

    secret_findings, config_findings, llm_result = None, None, None
    for t in tasks:
        if isinstance(t, Exception):
            continue
        if t and isinstance(t, tuple):
            if t[0] == "secret":
                secret_findings = t[1]
            elif t[0] == "config":
                config_findings = t[1]
            elif t[0] == "llm":
                llm_result = t[1]

    if isinstance(tasks[0], Exception):
        logger.warning("tier1.secret_failed", error=str(tasks[0]))
        secret_findings = []
    if isinstance(tasks[1], Exception):
        logger.warning("tier1.config_failed", error=str(tasks[1]))
        config_findings = []
    if isinstance(tasks[2], Exception):
        logger.warning("tier1.llm_failed", error=str(tasks[2]))
        llm_result = LLMExtractResult(unverified=True)

    logger.info("tier1.analyze.done",
                 secrets=len(secret_findings or []),
                 configs=len(config_findings or []),
                 llms=len(llm_result.findings if llm_result else []))

    all_findings = _merge_findings(
        secret_findings or [],
        config_findings or [],
        llm_result.findings if llm_result else [],
        ast_result,
    )

    result["findings"] = [_finding_to_dict(f) for f in all_findings]
    result["duration_ms"] = int((time.time() - start_time) * 1000)

    # Check if any analyzer failed → partial
    if (isinstance(tasks[0], Exception) or isinstance(tasks[1], Exception)
            or (llm_result and llm_result.unverified)):
        result["status"] = "partial"

    logger.info("tier1.complete", status=result["status"], findings=len(result["findings"]))
    return result


async def _run_secret_detector(repo_path: str, timeout: float) -> tuple:
    """Run secret detector with timeout. Returns ("secret", findings) or raises."""
    try:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, scan_directory, repo_path)
        findings = await asyncio.wait_for(future, timeout=timeout)
        return ("secret", findings)
    except asyncio.TimeoutError:
        logger.warning("tier1.secret_timeout")
        raise


async def _run_config_flaws(repo_path: str, stack: str, timeout: float) -> tuple:
    """Run config-flaw analyzer with timeout. Returns ("config", findings)."""
    try:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, analyze_config_flaws, repo_path, stack)
        findings = await asyncio.wait_for(future, timeout=timeout)
        return ("config", findings)
    except asyncio.TimeoutError:
        logger.warning("tier1.config_timeout")
        raise


async def _run_llm_extractor(ast_result: ParseResult, llm_client: Optional[LLMClient], timeout: float) -> tuple:
    """Run LLM extractor on extracted code segments. Returns ("llm", LLMExtractResult)."""
    try:
        loop = asyncio.get_running_loop()
        # Concatenate route files content for LLM analysis
        code_snippets = "\n\n".join([
            f"// File: {route.file}\n// Path: {route.path}\n// Methods: {','.join(route.methods)}"
            for route in ast_result.routes
        ][:50])  # cap at 50 routes to stay under token budget

        if not code_snippets:
            return ("llm", LLMExtractResult(findings=[]))

        client = llm_client or LLMClient()
        def _call():
            return analyze_code(code_snippets, llm_client=client, max_retries=2)

        future = loop.run_in_executor(None, _call)
        result = await asyncio.wait_for(future, timeout=timeout)
        return ("llm", result)
    except asyncio.TimeoutError:
        logger.warning("tier1.llm_timeout")
        raise


# ─── Finding merging ───

def _merge_findings(
    secret_findings: list,
    config_findings: list,
    llm_findings: list,
    ast_result: ParseResult,
) -> list:
    """Merge findings from all analyzers. Deduplicate by file+line+title."""
    merged = []
    seen = set()

    # Secret findings
    for sf in secret_findings:
        try:
            key = (getattr(sf, "file", ""), getattr(sf, "line", 0), getattr(sf, "key_type", ""))
        except Exception:
            continue
        if key not in seen:
            seen.add(key)
            merged.append({
                "source": "secret_detector",
                "severity": getattr(sf, "severity", "info"),
                "title": f"Secret: {getattr(sf, 'key_type', 'unknown')}",
                "file": getattr(sf, "file", ""),
                "line": getattr(sf, "line", 0),
                "evidence": getattr(sf, "evidence", ""),
            })

    # Config-flaw findings
    for cf in config_findings:
        try:
            key = (getattr(cf, "file", ""), getattr(cf, "line", 0), getattr(cf, "rule_id", ""))
        except Exception:
            continue
        if key not in seen:
            seen.add(key)
            sev = getattr(cf, "severity", "info")
            sev_str = sev.value if hasattr(sev, "value") else str(sev)
            merged.append({
                "source": "config_flaws",
                "severity": sev_str,
                "title": getattr(cf, "title", ""),
                "file": getattr(cf, "file", ""),
                "line": getattr(cf, "line", 0),
                "patch_md": getattr(cf, "patch_md", ""),
                "evidence": getattr(cf, "evidence", ""),
            })

    # LLM findings
    for lf in llm_findings:
        try:
            key = (str(getattr(lf, "line", 0)), getattr(lf, "flaw", ""))
        except Exception:
            continue
        if key not in seen:
            seen.add(key)
            merged.append({
                "source": "llm_extractor",
                "model": getattr(lf, "model", "unknown"),
                "severity": getattr(lf, "severity", "info"),
                "title": getattr(lf, "flaw", ""),
                "line": getattr(lf, "line", 0),
                "evidence": getattr(lf, "evidence", ""),
                "suggestion": getattr(lf, "suggestion", ""),
            })

    return merged


def _finding_to_dict(finding: dict) -> dict:
    return finding


# ─── Sync wrapper for tests ───

def run_tier1_sync(repo_url: str, branch: str = "HEAD", llm_client=None) -> dict:
    return asyncio.run(run_tier1(repo_url, branch, llm_client))
