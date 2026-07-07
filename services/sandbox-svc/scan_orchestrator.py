"""End-to-end scan pipeline orchestrator.

Chains Tier 1 (static) -> Tier 2 (sandbox) with graceful degradation
at each stage and structured logging for observability.

Pipeline:
  1. Clone repo (handled internally by run_tier1)
  2. Run Tier 1 static analysis
  3. If stack is Next.js/Express: run Tier 2 sandbox scan
  4. Persist findings to Supabase
  5. Update scan status through each stage

Error handling:
  - Invalid URL -> 400
  - Clone failed -> 400 (via Tier 1 returning error status)
  - Tier 1 failed -> 500, full error logged
  - Tier 2 failed -> return Tier 1 findings (graceful degradation)
  - Supabase write failure -> retry 2x, then log and continue

Stateless between requests: all scan state lives in Supabase.
"""

import asyncio
import json
import os
import time
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

import structlog

from circuit_breaker import CircuitBreaker, CircuitState
from sandbox.tier2 import Tier2Result, run_tier2
from sandbox.local_runner import LocalDockerClient
from sb_client import get_supabase_client
from scanner.clone import CloneError, RepoTooLarge
from scanner.tier1 import run_tier1

logger = structlog.get_logger(__name__)

TIER2_STACKS = {"nextjs", "express"}
MAX_DB_RETRIES = 2
FLY_MACHINE_COST_PER_SEC = 0.00000444
LLM_INPUT_COST_PER_M = 3.0
LLM_OUTPUT_COST_PER_M = 15.0


def validate_repo_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def start_scan(repo_url: str, fly_client=None) -> dict:
    if not validate_repo_url(repo_url):
        return {"error": "Invalid repo URL. Must be an HTTP(S) GitHub URL."}, 400

    if fly_client is None and "FLY_API_TOKEN" not in os.environ:
        try:
            fly_client = LocalDockerClient()
            logger.info("scan.local_mode", transport="docker")
        except Exception as e:
            logger.warning("scan.local_mode_disabled", error=str(e))
            fly_client = None

    scan_id = str(uuid.uuid4())
    created_at = _now_iso()

    sb = get_supabase_client(service_role=True)
    try:
        sb.table("scans").insert({
            "id": scan_id,
            "repo_url": repo_url,
            "status": "queued",
            "created_at": created_at,
        }).execute()
    except Exception as e:
        logger.error("scan.db_insert_failed", scan_id=scan_id, error=str(e))
        return {"error": "Failed to create scan record"}, 500

    asyncio.create_task(_run_pipeline(scan_id, repo_url, sb, fly_client))

    return {"scan_id": scan_id, "status": "queued", "created_at": created_at}


async def _run_pipeline(scan_id: str, repo_url: str, sb, fly_client=None):
    start_time = time.monotonic()
    tier1_findings = []
    tier2_findings = []
    stack = ""
    total_duration = 0

    breaker = CircuitBreaker()
    breaker_state = CircuitState()
    machine_seconds = 0.0
    llm_tokens_in = 0
    llm_tokens_out = 0

    def _update_status(status: str, **extra):
        try:
            sb.table("scans").update({"status": status, **extra}).eq("id", scan_id).execute()
        except Exception as e:
            logger.warning("scan.status_update_failed", scan_id=scan_id, status=status, error=str(e))

    async def _save_with_retry(data: dict):
        for attempt in range(1, MAX_DB_RETRIES + 2):
            try:
                sb.table("scans").update(data).eq("id", scan_id).execute()
                return
            except Exception as e:
                if attempt <= MAX_DB_RETRIES:
                    logger.warning("scan.db_retry", scan_id=scan_id, attempt=attempt, error=str(e))
                    await asyncio.sleep(0.5 * attempt)
                else:
                    logger.error("scan.db_save_failed", scan_id=scan_id, error=str(e))

    try:
        _update_status("cloning")
        logger.info("scan.started", scan_id=scan_id, repo_url=repo_url)

        tier1_start = time.monotonic()
        tier1_result = await run_tier1(repo_url)
        tier1_duration = int((time.monotonic() - tier1_start) * 1000)

        if tier1_result.get("status") == "error":
            err = tier1_result.get("error", "Tier 1 analysis failed")
            logger.error("scan.tier1_failed", scan_id=scan_id, error=err, duration_ms=tier1_duration)
            _update_status("failed", error="Analysis failed")
            return

        tier1_findings = tier1_result.get("findings", [])
        stack = tier1_result.get("stack", "")
        repo_path = tier1_result.get("repo", "")

        llm_usage = tier1_result.get("llm_usage", {})
        if llm_usage:
            llm_tokens_in = llm_usage.get("tokens_in", 0)
            llm_tokens_out = llm_usage.get("tokens_out", 0)
            llm_cost_cents = llm_usage.get("cost_cents", 0.0)
            breaker.record_tokens(breaker_state, llm_tokens_in + llm_tokens_out)
            breaker.record_cost(breaker_state, llm_cost_cents)

        logger.info(
            "scan.tier1_complete",
            scan_id=scan_id,
            finding_count=len(tier1_findings),
            duration_ms=tier1_duration,
        )

        if stack in TIER2_STACKS and repo_path:
            if not breaker.check(breaker_state):
                logger.warning("scan.tier2_skipped_breaker", scan_id=scan_id, reason=breaker_state.trip_reason)
            else:
                logger.info("scan.tier2_start", scan_id=scan_id, stack=stack)
                _update_status("tier2")
                tier2_start = time.monotonic()

                try:
                    tier2_result = await run_tier2(
                        repo_path=repo_path,
                        stack=stack,
                        auth_stack="custom",
                        fly_client=fly_client,
                        supabase_client=sb,
                    )
                    tier2_end = time.monotonic()
                    tier2_duration = int((tier2_end - tier2_start) * 1000)
                    machine_seconds = (tier2_end - tier2_start)

                    if tier2_result.status == "complete":
                        tier2_findings = _serialize_tier2_result(tier2_result)
                        logger.info(
                            "scan.tier2_complete",
                            scan_id=scan_id,
                            finding_count=len(tier2_findings),
                            duration_ms=tier2_duration,
                        )
                    else:
                        logger.warning(
                            "scan.tier2_degraded",
                            scan_id=scan_id,
                            status=tier2_result.status,
                            error=tier2_result.error,
                            duration_ms=tier2_duration,
                        )
                except Exception as e:
                    logger.warning("scan.tier2_exception", scan_id=scan_id, error=str(e))
        else:
            logger.info("scan.tier2_skipped", scan_id=scan_id, stack=stack or "none")

        total_findings = len(tier1_findings) + len(tier2_findings)
        total_duration = int((time.monotonic() - start_time) * 1000)

        machine_cost_cents = machine_seconds * FLY_MACHINE_COST_PER_SEC * 100
        llm_cost_cents = (llm_tokens_in * LLM_INPUT_COST_PER_M / 1_000_000 + llm_tokens_out * LLM_OUTPUT_COST_PER_M / 1_000_000) * 100
        total_cost_cents = round(machine_cost_cents + llm_cost_cents, 4)

        await _save_with_retry({
            "tier1_findings": json.dumps(tier1_findings),
            "tier2_findings": json.dumps(tier2_findings) if tier2_findings else None,
            "total_findings": total_findings,
            "duration_ms": total_duration,
            "stack": stack,
            "status": "completed",
            "cost_cents": total_cost_cents,
            "machine_seconds": round(machine_seconds, 3),
            "llm_tokens_in": llm_tokens_in,
            "llm_tokens_out": llm_tokens_out,
        })

        logger.info(
            "scan.completed",
            scan_id=scan_id,
            total_findings=total_findings,
            total_duration_ms=total_duration,
        )

    except (RepoTooLarge, CloneError) as e:
        logger.error("scan.clone_failed", scan_id=scan_id, error=str(e))
        _update_status("failed", error=str(e))
    except Exception as e:
        logger.error("scan.pipeline_error", scan_id=scan_id, error=str(e))
        _update_status("failed", error="Internal scan error")


def _serialize_tier2_result(result: Tier2Result) -> list[dict]:
    entries = []
    for route in result.routes:
        try:
            entries.append({
                "path": getattr(route, "path", ""),
                "methods": getattr(route, "methods", []),
                "auth_required": getattr(route, "auth_required", False),
                "auth_stack": getattr(route, "auth_stack", ""),
                "file_path": getattr(route, "file_path", ""),
                "line": getattr(route, "line", 0),
            })
        except Exception:
            continue
    return entries


async def get_scan(scan_id: str) -> dict | None:
    try:
        sb = get_supabase_client(service_role=True)
        result = sb.table("scans").select("*").eq("id", scan_id).execute()
        if not result.data:
            return None
        row = dict(result.data[0])
        tier1_raw = row.pop("tier1_findings", None)
        tier2_raw = row.pop("tier2_findings", None)
        row["tier1_findings"] = json.loads(tier1_raw) if isinstance(tier1_raw, str) else (tier1_raw or [])
        row["tier2_findings"] = json.loads(tier2_raw) if isinstance(tier2_raw, str) else (tier2_raw or [])
        return row
    except Exception as e:
        logger.error("scan.get_failed", scan_id=scan_id, error=str(e))
        return None


async def get_scan_status(scan_id: str) -> dict | None:
    try:
        sb = get_supabase_client(service_role=True)
        result = sb.table("scans").select("id, repo_url, status, created_at, duration_ms, total_findings").eq("id", scan_id).execute()
        if not result.data:
            return None
        return dict(result.data[0])
    except Exception as e:
        logger.error("scan.status_get_failed", scan_id=scan_id, error=str(e))
        return None
