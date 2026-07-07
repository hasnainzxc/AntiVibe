"""Tier 2 orchestrator — chains containerize→seed→spin→forge→handoff.

Architecture
------------
This module is the Wave 3 orchestrator that ties together all the
sandbox building blocks into a single async pipeline:

    1. Containerize  — generate + write Dockerfile to scratch dir
    2. Seed          — seed_postgres (live) or seed_to_json (offline)
    3. Spin          — SandboxSpinup.run() → SandboxHandle
    4. Health        — SandboxHealthMonitor.health() → verify boot
    5. Forge         — jwt_forge.forge() → (User_A token, User_B token)
    6. Route index   — route_mapper.build_index_from_repo()
    7. Merge         — assemble Tier2Result

The entire chain runs under a 300-second circuit-breaker. If any
step exceeds the budget, the orchestrator returns a partial result
with `status="partial"` and whatever intermediate outputs were
collected before the timeout.

Design rationale
----------------
- `asyncio.wait_for` wraps the entire chain. This is simpler than
  per-step timeouts and matches the real-world constraint: the
  caller cares about total wall-clock time, not individual step
  durations. A cold-boot sandbox + DB seed can legitimately take
  2-3 minutes; 300s gives headroom without letting a hung machine
  block the event loop indefinitely.
- Intermediate state is tracked in a mutable `_StageState` dict so
  the timeout handler can extract partial results. Without this,
  a timeout during step 5 would lose the handle from step 3.
- Step failures are caught per-step and logged. The first failure
  short-circuits the chain and returns `status="error"` with the
  error message. This is preferable to letting exceptions propagate
  because the caller (Wave 4 scan orchestrator) needs a structured
  result, not a stack trace.
- The `fly_client` and `supabase_client` are optional constructor
  args. When None, the orchestrator skips steps that require them
  (spin, health, audit log) and returns a partial result. This
  lets tests run without any real infrastructure.

Dependency map
--------------
- Reads from: sandbox.containerize, sandbox.seeder, sandbox.spinup,
              sandbox.jwt_forge, sandbox.health_monitor,
              sandbox.route_mapper.
- Reads from: fly.client.FlyClient (injected), Supabase client
              (injected).
- Writes to: scratch directory (containerize output), Supabase
              audit log (via spinup).
- Consumed by: the Wave 4 scan orchestrator.

Testing
-------
- `tests/sandbox/test_tier2.py` covers: full chain, circuit-breaker
  timeout, seed failure, spinup failure, health check failure.
  All deps are mocked — no real Fly machines, no real Supabase,
  no real DB.
"""

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import structlog

from sandbox.containerize import generate_dockerfile, write_dockerfile
from sandbox.local_runner import LocalDockerClient
from sandbox.seeder import SeedResult, seed_postgres, seed_to_json
from sandbox.spinup import SandboxHandle, SandboxSpinup
from sandbox.jwt_forge import ForgedToken, forge as jwt_forge
from sandbox.health_monitor import SandboxHealth, SandboxHealthMonitor
from sandbox.route_mapper import RouteIndexEntry, build_index_from_repo

logger = structlog.get_logger(__name__)

# Circuit-breaker timeout. 300s (5 min) covers cold-boot + DB seed
# with generous headroom. A typical run is 30-90s; 300s is the
# "something is seriously wrong" threshold.
TIER2_TIMEOUT = 300


@dataclass
class Tier2Result:
    """Aggregate output of the Tier 2 orchestrator.

    Fields:
        handle:      SandboxHandle from the spin-up step. None if
                     the chain failed before or during spin-up.
        tokens:      (User_A token, User_B token) from the forge
                     step. None if the chain failed before forge.
        routes:      Route index entries from the route mapper.
                     Empty list if the chain failed before route
                     indexing.
        health:      SandboxHealth snapshot from the health check.
                     None if the chain failed before health check.
        duration_ms: Total wall-clock time in milliseconds. Measured
                     with `time.monotonic` (immune to wall-clock
                     skew).
        status:      One of "complete" (all steps succeeded),
                     "partial" (timeout before completion), or
                     "error" (a step raised an exception).
        error:       Error message if `status="error"`. None
                     otherwise. Carries the exception string from
                     the failing step so the caller can log it
                     without re-deriving.
    """

    handle: Optional[SandboxHandle] = None
    tokens: Optional[tuple[ForgedToken, ForgedToken]] = None
    routes: list[RouteIndexEntry] = field(default_factory=list)
    health: Optional[SandboxHealth] = None
    duration_ms: int = 0
    status: str = "complete"
    error: Optional[str] = None


async def _run_chain(
    repo_path: str,
    stack: Any,
    auth_stack: str,
    fly_client: Any,
    supabase_client: Any,
    state: dict,
) -> Tier2Result:
    """Execute the 6-step chain. Mutates `state` for partial extraction.

    Each step writes its output into `state` before proceeding to
    the next. On timeout, the caller reads `state` to build a
    partial Tier2Result.

    Args:
        repo_path: Path to the cloned repo.
        stack: Detected stack enum (scanner.detect_stack.Stack).
        auth_stack: Auth library string ("nextauth", "clerk", etc.).
        fly_client: FlyClient instance (or AsyncMock in tests).
        supabase_client: Supabase client (or MagicMock in tests).
        state: Mutable dict for intermediate results. Keys:
            "dockerfile_path", "seed_result", "handle", "health",
            "tokens", "routes".

    Returns:
        Tier2Result with status="complete" on success.

    Raises:
        Exception: any step failure propagates to the caller
            (run_tier2 catches it and returns status="error").
    """
    repo_root = Path(repo_path)
    scratch_dir = repo_root / ".antivibe-scratch"

    # ─── Step 1: Containerize ───
    # Generate Dockerfile content and write to scratch dir.
    # The scratch dir is separate from the user's repo so the
    # scanner never mutates user code.
    dockerfile_content = generate_dockerfile(stack, repo_root)
    dockerfile_path = write_dockerfile(stack, repo_root, scratch_dir)
    state["dockerfile_path"] = dockerfile_path
    logger.info(
        "tier2.containerize.done",
        stack=str(stack),
        dockerfile=str(dockerfile_path),
        bytes=len(dockerfile_content),
    )

    local_docker = fly_client if isinstance(fly_client, LocalDockerClient) else None
    image_ref = "antivibe-sandbox:latest"
    if local_docker:
        image_ref = local_docker.build_image(repo_root, dockerfile_path)

    # ─── Step 2: Seed ───
    # Choose seeder based on env. DATABASE_URL present → live
    # Postgres seed; otherwise → offline JSON seed. The JSON
    # path is the primary test surface; the Postgres path is
    # for end-to-end runs with a real DB.
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        seed_result_dict = await seed_postgres(database_url)
        # seed_postgres returns a dict, not a SeedResult. Wrap
        # it so the forge step can consume it uniformly.
        seed_result = SeedResult(
            postgres=seed_result_dict,
            firestore={},
            users=[],
        )
    else:
        seed_result = seed_to_json(scratch_dir)
    state["seed_result"] = seed_result
    logger.info(
        "tier2.seed.done",
        users=len(seed_result.users),
        postgres_rows=seed_result.postgres,
    )

    # ─── Step 3: Spin ───
    # Construct SandboxSpinup with injected deps and run the
    # spin-up flow. The containerizer_fn and seeder_fn are
    # wired to the real functions; the fly_client and
    # supabase_client are passed through from the caller.
    spinup = SandboxSpinup(
        fly_client=fly_client,
        supabase_client=supabase_client,
        containerizer_fn=generate_dockerfile,
        seeder_fn=_async_seed_wrapper(seed_result),
    )
    handle = await spinup.run(
        scan_id="tier2-scan",
        repo_root=repo_root,
        stack=stack,
        image_ref=image_ref,
    )
    if local_docker:
        local_url = local_docker.get_container_url(handle.machine_id)
        handle = SandboxHandle(
            machine_id=handle.machine_id,
            sandbox_url=local_url,
            seed_credentials=handle.seed_credentials,
        )
    state["handle"] = handle
    logger.info(
        "tier2.spin.done",
        machine_id=handle.machine_id,
        sandbox_url=handle.sandbox_url,
    )

    # ─── Step 4: Health ───
    # Verify the machine reached "started" state. The health
    # monitor polls fly_client.wait_for_running internally;
    # we just need to check the `ready` flag.
    health_monitor = SandboxHealthMonitor(fly_client=fly_client)
    health = await health_monitor.health(machine_id=handle.machine_id)
    state["health"] = health
    if not health.ready:
        raise RuntimeError(
            f"Sandbox health check failed: machine {handle.machine_id} "
            f"did not reach 'started' within timeout"
        )
    logger.info(
        "tier2.health.done",
        machine_id=handle.machine_id,
        boot_duration_ms=health.boot_duration_ms,
        ready=health.ready,
    )

    # ─── Step 5: Forge ───
    # Mint JWTs for USER_A and USER_B using the detected auth
    # stack. The forge function reads the seed_result to find
    # the user rows and mints tokens with the appropriate
    # algorithm (HS256/RS256) for the auth library.
    env_root = os.environ.copy()
    token_a, token_b = jwt_forge(
        env_root=env_root,
        auth_stack=auth_stack,
        seed_result=seed_result,
    )
    state["tokens"] = (token_a, token_b)
    logger.info(
        "tier2.forge.done",
        auth_stack=auth_stack,
        user_a=token_a.user_id,
        user_b=token_b.user_id,
    )

    # ─── Step 6: Route index ───
    # Parse the repo AST and build the route index. This is
    # a pure function with no side effects; it reads source
    # files to detect auth patterns and normalize paths.
    stack_str = stack.value if hasattr(stack, "value") else str(stack)
    routes = build_index_from_repo(
        repo_path=repo_path,
        stack=stack_str,
        auth_stack=auth_stack,
    )
    state["routes"] = routes
    logger.info(
        "tier2.routes.done",
        count=len(routes),
        stack=stack_str,
    )

    # ─── Step 7: Merge ───
    # All steps succeeded. Assemble the final result.
    return Tier2Result(
        handle=handle,
        tokens=(token_a, token_b),
        routes=routes,
        health=health,
        duration_ms=state["start_ms"],  # placeholder; caller overwrites
        status="complete",
        error=None,
    )


def _async_seed_wrapper(seed_result: SeedResult):
    """Return an async fn that yields the pre-computed SeedResult.

    SandboxSpinup expects an async seeder_fn. In the tier2 flow,
    we've already run the seeder (step 2) before constructing
    the spinup. This wrapper lets us pass the result through
    without re-running the seed.

    Args:
        seed_result: The SeedResult from step 2.

    Returns:
        An async callable that returns the seed_result.
    """

    async def _seeder(repo_root: Path) -> SeedResult:
        return seed_result

    return _seeder


async def run_tier2(
    repo_path: str,
    stack: Any,
    auth_stack: str,
    fly_client: Any = None,
    supabase_client: Any = None,
) -> Tier2Result:
    """Run the Tier 2 orchestrator with a 300s circuit-breaker.

    Chains containerize→seed→spin→forge→health→route_index and
    returns a Tier2Result. On timeout, returns a partial result
    with whatever intermediate outputs were collected. On step
    failure, returns an error result with the exception message.

    Args:
        repo_path: Path to the cloned repo (string, not Path).
        stack: Detected stack enum (scanner.detect_stack.Stack).
        auth_stack: Auth library string ("nextauth", "clerk", etc.).
        fly_client: FlyClient instance. Optional; if None, spin
                    and health steps are skipped (partial result).
        supabase_client: Supabase client. Optional; if None, audit
                         log is skipped.

    Returns:
        Tier2Result with:
            - status="complete" if all steps succeeded.
            - status="partial" if the 300s timeout fired.
            - status="error" if a step raised an exception.
    """
    start_time = time.monotonic()
    state: dict = {"start_ms": 0}  # placeholder; overwritten at end

    # If no fly_client, we can't spin or health-check. Return
    # early with a partial result rather than attempting steps
    # that will fail.
    if fly_client is None:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        return Tier2Result(
            handle=None,
            tokens=None,
            routes=[],
            health=None,
            duration_ms=duration_ms,
            status="partial",
            error="fly_client is None; cannot spin or health-check",
        )

    try:
        # Wrap the entire chain in a timeout. asyncio.wait_for
        # raises asyncio.TimeoutError if the coroutine does not
        # complete within TIER2_TIMEOUT seconds.
        result = await asyncio.wait_for(
            _run_chain(
                repo_path=repo_path,
                stack=stack,
                auth_stack=auth_stack,
                fly_client=fly_client,
                supabase_client=supabase_client,
                state=state,
            ),
            timeout=TIER2_TIMEOUT,
        )
        # Overwrite the placeholder duration with the real value.
        duration_ms = int((time.monotonic() - start_time) * 1000)
        result.duration_ms = duration_ms
        return result

    except asyncio.TimeoutError:
        # Circuit-breaker fired. Extract partial results from
        # the state dict. Whatever steps completed before the
        # timeout are preserved; the rest are None/empty.
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.warning(
            "tier2.timeout",
            duration_ms=duration_ms,
            timeout_s=TIER2_TIMEOUT,
        )
        return Tier2Result(
            handle=state.get("handle"),
            tokens=state.get("tokens"),
            routes=state.get("routes", []),
            health=state.get("health"),
            duration_ms=duration_ms,
            status="partial",
            error=f"Tier 2 timed out after {TIER2_TIMEOUT}s",
        )

    except Exception as e:
        # Step failure. Log and return error result.
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.error(
            "tier2.error",
            error=str(e),
            duration_ms=duration_ms,
        )
        return Tier2Result(
            handle=state.get("handle"),
            tokens=state.get("tokens"),
            routes=state.get("routes", []),
            health=state.get("health"),
            duration_ms=duration_ms,
            status="error",
            error=str(e),
        )
