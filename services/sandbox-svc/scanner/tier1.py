"""Tier 1 orchestrator: chain clone → detect → AST → parallel analyzers → merge.

This module is the *only* place that knows the order in which the
scanner stages run. Everything else in `scanner/` is a leaf module
that doesn't import any other scanner module; tier1.py is the spine
that connects them.

Pipeline shape
--------------

  ┌────────┐   ┌────────────┐   ┌─────────┐
  │ clone  │ → │ detect_    │ → │ AST     │
  │ (sync) │   │ stack      │   │ (sync)  │
  └────────┘   └────────────┘   └─────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │ asyncio.gather       │
                          │  • secret_detector   │
                          │  • config_flaws      │
                          │  • llm_extractor     │
                          └──────────────────────┘
                                     │
                                     ▼
                              merge + return

SLA and circuit-breaker
-----------------------
Tier 1's p95 budget is 5 minutes. The hard cap (`TIER1_TIMEOUT`)
is 60s — chosen as a *circuit-breaker*, not a *timeout*:

  - A scan that finishes in 60s is in-budget.
  - A scan that exceeds 60s is marked "partial": we return what
    we have so far and surface the time-out to the dashboard,
    rather than blocking the request thread and potentially
    triggering a cascade of stuck workers downstream.

The 60s number is small relative to a normal scan (clones take
~5–20s, AST parse ~2–10s, the parallel analyzers ~10–30s) but
tight enough that a runaway monorepo or a hung LLM call doesn't
pin a worker for minutes.
"""

import asyncio
import os
import shutil
import tempfile
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

# Circuit-breaker in seconds. Empirically: a healthy Tier 1 scan
# finishes in 20–40s. 60s leaves headroom for cold-image pulls of
# the runner container (one-time per VM) while still bailing out
# before a hung LLM call or a 5GB monorepo can pin a worker.
TIER1_TIMEOUT = 60


async def run_tier1(
    repo_url: str,
    branch: str = "HEAD",
    llm_client: Optional[LLMClient] = None,
) -> dict:
    """Run the full Tier 1 pipeline and return merged results.

    Pipeline stages:

      1. **clone** (sync, blocking): pulls the repo, applies the
         size cap and postinstall guardrails. If it fails with
         RepoTooLarge or CloneError, we short-circuit with
         `status="error"` — nothing downstream is meaningful.
      2. **detect_stack** (sync): picks one of 6 supported stacks.
         UnsupportedStackError → `status="error"`.
      3. **AST parse** (sync, blocking): must finish before the
         parallel analyzers, because the LLM stage consumes
         `ParseResult.routes` as its input. Failure here is logged
         but not fatal — `_parse_repo` returns an empty result
         and the analyzers still run.
      4. **circuit-breaker check**: if elapsed > TIER1_TIMEOUT,
         we return `status="partial"` with whatever we have.
      5. **parallel analyzers** (asyncio.gather): secret detector,
         config-flaw analyzer, and LLM extractor run concurrently
         each in their own thread via `run_in_executor`. Failures
         in any one are isolated — the other two still complete.
      6. **merge**: deduplicate by (file, line, key) and emit a
         flat list of finding dicts.

    Args:
        repo_url: GitHub HTTPS URL.
        branch: branch to clone (default: remote HEAD).
        llm_client: optional LLM client override. Tests pass a
            mock; production passes None and gets the real
            Anthropic-backed client.

    Returns:
        A dict with keys: `status`, `repo`, `stack`, `findings`,
        `duration_ms`, `error`. `status` is one of:
          - "complete": all stages ran without circuit-break.
          - "partial": at least one stage was skipped or failed,
            but the pipeline returned *some* findings.
          - "error": a fatal failure (clone or stack detection);
            `findings` is empty.
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
        if os.path.isdir(repo_url):
            repo_path = tempfile.mkdtemp(prefix="antivibe-local-")
            shutil.copytree(repo_url, repo_path, dirs_exist_ok=True)
            logger.info("tier1.clone.local_copy", src=repo_url, dest=repo_path)
        else:
            repo_path = clone_repo(repo_url, branch=branch)
        result["repo"] = repo_path
        logger.info("tier1.clone.done", path=repo_path)

    except RepoTooLarge as e:
        # RepoTooLarge is a *fast-fail* path: the cap is enforced
        # before we even try to clone, so this typically returns
        # in <1s. We log without a stack trace because there's
        # nothing actionable for the operator.
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
        # We deliberately don't try the next-best stack or fall
        # back to a generic scan — every analyzer is stack-tuned,
        # so misclassifying would generate noise that costs more
        # in operator time than it saves in scan time.
        logger.error("tier1.unsupported_stack", error=str(e))
        result["status"] = "error"
        result["error"] = str(e)
        result["duration_ms"] = int((time.time() - start_time) * 1000)
        return result

    # AST parse must complete before parallel analyzers because
    # the LLM stage consumes ParseResult.routes as its input.
    # `parse_repo` itself returns an empty ParseResult on failure
    # rather than raising — we log and continue.
    logger.info("tier1.ast.start")
    ast_result: ParseResult = parse_repo(repo_path, stack.value)
    logger.info("tier1.ast.done", routes=len(ast_result.routes), env_refs=len(ast_result.env_refs))

    # Circuit-breaker: if we've already blown the budget getting
    # here, abort the parallel analyzers and return what we have.
    # The 60s cap is per the module docstring: a 5min Tier 1 p95
    # means individual scans should not exceed 60s.
    elapsed = time.time() - start_time
    if elapsed > TIER1_TIMEOUT:
        logger.warning("tier1.circuit_breaker", elapsed=elapsed)
        result["status"] = "partial"
        result["duration_ms"] = int(elapsed * 1000)
        return result

    logger.info("tier1.analyze.start")
    # The `max(5, ...)` floor ensures even an already-overrun
    # pipeline gets at least 5s to make progress on the analyzers
    # — without it, a slow AST parse would starve the analyzers
    # of any budget at all.
    remaining = max(TIER1_TIMEOUT - elapsed, 5)

    try:
        # `return_exceptions=True` is critical: it converts each
        # task's exception into a returned exception value, so a
        # single failed analyzer (e.g. a hung LLM call) doesn't
        # cancel the other two. We inspect the results after
        # gather() to decide partial vs. complete.
        tasks = await asyncio.gather(
            _run_secret_detector(repo_path, remaining),
            _run_config_flaws(repo_path, stack.value, remaining),
            _run_llm_extractor(ast_result, llm_client, remaining),
            return_exceptions=True,
        )
    except TimeoutError:
        # `asyncio.gather` only raises on cancellation, not on
        # individual task timeouts (those surface via the task
        # itself with return_exceptions=True). This branch
        # triggers only if the *event loop* itself is cancelled.
        logger.error("tier1.analyzers_timeout")
        result["status"] = "partial"
        result["duration_ms"] = int((time.time() - start_time) * 1000)
        return result

    # Tag-and-bag dispatch. Each task returns a (label, payload)
    # tuple OR raises (caught by return_exceptions). We pair
    # the result with its analyzer by inspecting the label,
    # which is the only safe way given the heterogeneous return
    # types (list vs. LLMExtractResult).
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

    # Per-analyzer failure handling. An exception in a task means
    # the analyzer raised or timed out; we treat that as "no
    # findings from this stage" and let the status-flip at the
    # bottom mark the run as partial. The order matches the
    # gather() positional order: secret / config / llm.
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

    if llm_result and not llm_result.unverified:
        result["llm_usage"] = {
            "tokens_in": llm_result.tokens_in,
            "tokens_out": llm_result.tokens_out,
            "cost_cents": llm_result.cost_cents,
        }

    # Promote to "partial" if any analyzer failed. The LLM also
    # counts as a partial failure when it returned unverified —
    # i.e. we reached it but the model gave us nothing usable,
    # which is a different signal from a network timeout.
    if (isinstance(tasks[0], Exception) or isinstance(tasks[1], Exception)
            or (llm_result and llm_result.unverified)):
        result["status"] = "partial"

    logger.info("tier1.complete", status=result["status"], findings=len(result["findings"]))
    return result


async def _run_secret_detector(repo_path: str, timeout: float) -> tuple:
    """Run the secret detector in a thread, with a timeout.

    Returns `("secret", findings)`. Raises asyncio.TimeoutError
    on timeout — the caller catches via `return_exceptions=True`.

    The detector is sync and CPU+IO bound (file walks + regex
    on every file); running it in the default executor keeps
    the event loop responsive for the other two analyzers.
    """
    try:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, scan_directory, repo_path)
        findings = await asyncio.wait_for(future, timeout=timeout)
        return ("secret", findings)
    except asyncio.TimeoutError:
        logger.warning("tier1.secret_timeout")
        raise


async def _run_config_flaws(repo_path: str, stack: str, timeout: float) -> tuple:
    """Run the config-flaw analyzer in a thread, with a timeout.

    Returns `("config", findings)`. Same executor pattern as
    `_run_secret_detector` — keeps the loop free for the LLM
    stage. The `stack` arg is unused at the moment; passed
    for future stack-gated analyzers.
    """
    try:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, analyze_config_flaws, repo_path, stack)
        findings = await asyncio.wait_for(future, timeout=timeout)
        return ("config", findings)
    except asyncio.TimeoutError:
        logger.warning("tier1.config_timeout")
        raise


async def _run_llm_extractor(ast_result: ParseResult, llm_client: Optional[LLMClient], timeout: float) -> tuple:
    """Run the LLM extractor on the route files surfaced by AST parse.

    Concatenates up to 50 routes into a single prompt. The cap is a
    token-budget guard: 50 routes at ~200 tokens each = 10K input
    tokens, which fits in Claude's context with the system prompt
    and leaves room for the response. Beyond 50 routes, the value
    per additional route drops sharply (the LLM is pattern-matching
    on common auth-bypass shapes, not exhaustively cataloging).

    Returns `("llm", LLMExtractResult)`. The empty-routes case
    short-circuits to an empty result so we don't burn an LLM call
    on a repo with no API surface.
    """
    try:
        loop = asyncio.get_running_loop()
        # Concatenate route files content for LLM analysis.
        # Each route becomes a 3-line comment header (file, path,
        # methods) — the LLM uses the path/methods to understand
        # which routes to investigate, then reads the file body
        # we attach below.
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
    """Merge findings from all analyzers into a single flat list.

    Dedup key varies by source because the analyzers don't all
    share a common keyspace:

      - secret:   (file, line, key_type) — the same secret in
        two files is two findings; the same secret on the same
        line is one.
      - config:   (file, line, rule_id) — same rule firing twice
        on the same line is one finding.
      - llm:      (line, flaw) — LLM findings don't have a
        reliable `file` (the model paraphrases path references
        in its evidence field), so we use line+flaw as the
        dedup key.

    `getattr(..., default)` is used liberally because findings
    can come from dataclasses OR from the test suite's mock
    classes (see `tests/scanner/test_tier1.py::TestMergeFindings`).
    The bare `except Exception` per finding swallows any
    attribute access failure — a single malformed finding
    should not lose the others.
    """
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
            # Severity may be the enum or a plain string
            # depending on whether the finding came from
            # the analyzer or a test mock. Normalize to
            # the enum's `.value` (or the raw string).
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
            # Cast line to str for the key tuple — the LLM
            # sometimes returns a numeric line as a string
            # and a direct equality check would miss the
            # dedup otherwise.
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
    """Identity passthrough. Exists as a separate function so the
    `result["findings"] = [_finding_to_dict(f) for f in all_findings]`
    line above has a single point of transformation when we later
    need to redact PII, add a stable `id` field, or normalize
    severity casing. Don't delete without checking the test
    suite (some tests may monkeypatch this hook).
    """
    return finding


# ─── Sync wrapper for tests ───

def run_tier1_sync(repo_url: str, branch: str = "HEAD", llm_client=None) -> dict:
    """Synchronous wrapper around `run_tier1` for tests and CLI callers.

    Uses `asyncio.run` which creates a fresh event loop per call —
    safe for the test suite but NOT safe to call from inside an
    already-running event loop. Production callers (the API
    handler) should call `run_tier1` directly and `await` it.
    """
    return asyncio.run(run_tier1(repo_url, branch, llm_client))
