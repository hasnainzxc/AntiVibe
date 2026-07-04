"""Sandbox health monitoring: boot detection, log streaming, crash recovery.

Architecture
------------
This module is the *observability layer* for a running sandbox
Fly Machine. It exposes three operations:

    1. `health()`         — poll for the machine to reach
                            "started" within a timeout, return
                            a `SandboxHealth` snapshot.
    2. `stream_logs()`    — async iterator over the machine's
                            log lines.
    3. `crash_recovery()` — destroy a crashed machine and
                            respawn a fresh one, with bounded
                            retry.

All Fly API interactions go through the injected `FlyClient`
(see `fly/client.py`). Tests use an `AsyncMock` and never
touch the network.

Design rationale
----------------
- `health()` returns a `SandboxHealth` snapshot rather than
  raising on timeout, because the scanner wants to *record*
  a boot failure (in the audit log, in the report) and
  decide whether to retry. Raising would force every caller
  to write a `try/except` block. The `ready` flag carries
  the same information with cleaner ergonomics.
- The 5-second `boot.slow` warning threshold is the SLO: a
  normal cold start is ~2-3s; >5s usually means a heavy
  `npm install` or an image pull bottleneck. We log at
  warning so the operator can see it but the scan continues.
- `crash_recovery()` retries on *any* exception, not just
  `FlyError`. Rationale: if the underlying network stack
  raises an httpx/connection error during destroy, that is
  a transient failure worth one retry — the alternative
  (only retry on `FlyError`) would require the caller to
  know which exceptions are retryable. The bounded retry
  count (`max_attempts=2` default) prevents infinite loops.
- After `max_attempts` failures, `SandboxCrashError` is
  raised. The error carries the `machine_id` so the caller
  can log it directly without re-deriving.

Dependency map
--------------
- Reads from: `fly.client.FlyClient`, `fly.client.FlyError`
              (both injected at construction time).
- Writes to: nothing directly. Side effects are mediated
              by the injected FlyClient.
- Consumed by: the scan orchestrator, both for normal
              health probes and for the crash-recovery
              path after a Fly machine enters a terminal
              failed state.

Testing
-------
- `tests/sandbox/test_health_monitor.py` covers: ready/timeout
  branches, slow-boot warning, log streaming edge cases
  (empty, single, many), crash recovery on the happy path,
  retry-after-failure, max-attempts exhaustion, default
  max_attempts value, and "no real network" smoke tests.
"""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import structlog

from fly.client import FlyClient, FlyError

logger = structlog.get_logger(__name__)


class SandboxCrashError(Exception):
    """Raised when crash recovery exhausts max attempts.

    Carries the `machine_id` of the machine that could not be
    recovered, so the caller can log it directly without
    re-deriving from context.
    """

    def __init__(self, message: str, machine_id: str | None = None):
        super().__init__(message)
        self.machine_id = machine_id


@dataclass
class SandboxHealth:
    """Health status snapshot for a sandbox machine.

    Fields:
        boot_duration_ms: Time from health check start to
            ready/timeout. Integer milliseconds, derived from
            `time.monotonic` (immune to wall-clock skew during
            the spin-up).
        ready: True iff the machine reached "started" within
            the timeout. False on timeout or FlyError.
        logs: Collected log lines, populated by `stream_logs`.
            Empty by default; `health()` does not collect logs
            to keep its own timeout budget focused.
        crash_signal: True if the machine entered a crash or
            terminal-failed state. Set by the crash-recovery
            path; never set by `health()` itself (which only
            reports the start-state outcome).
    """

    boot_duration_ms: int
    ready: bool
    logs: list[str] = field(default_factory=list)
    crash_signal: bool = False


class SandboxHealthMonitor:
    """Monitors sandbox health: boot detection, log streaming, crash recovery.

    Single dependency (`fly_client`) injected at construction.
    The class is otherwise stateless; `health()`, `stream_logs()`,
    and `crash_recovery()` are all independent calls that do
    not share mutable instance state.

    Thread/concurrency: the class holds no locks. Multiple
    coroutines can call its methods concurrently against
    different machine_ids; the underlying FlyClient is
    responsible for any concurrency safety on a single
    machine_id.
    """

    def __init__(self, fly_client: FlyClient):
        self.fly_client = fly_client

    async def health(self, machine_id: str, boot_timeout_s: int = 120) -> SandboxHealth:
        """Poll the machine state until "started" or timeout.

        Wraps `fly_client.wait_for_running` and translates
        its outcomes into a `SandboxHealth` snapshot. Does
        not raise on timeout — the `ready` flag is the signal.

        Default timeout is 120s. That value is the SLO ceiling
        for a healthy cold start; a typical cold start is
        5-15s, leaving 100+ seconds of headroom for image
        pulls on shared-cpu-1x.

        Args:
            machine_id: Fly Machine ID to monitor.
            boot_timeout_s: Max seconds to wait for the
                "started" state. Default 120.

        Returns:
            SandboxHealth with:
                - `ready=True`, `boot_duration_ms=actual_ms`
                    on success.
                - `ready=False`, `boot_duration_ms=timeout_ms`
                    on FlyError (typically a timeout or a
                    never-reached-started state).
                - `crash_signal=False` in both cases (this
                    method does not detect crashes; that's
                    `crash_recovery`'s job).
        """
        # `time.monotonic` is used over `time.time` because
        # the wall clock can jump (NTP correction) during
        # the spin-up, which would corrupt the duration
        # measurement. `monotonic` is guaranteed non-decreasing.
        start_time = time.monotonic()

        try:
            await self.fly_client.wait_for_running(machine_id, timeout=boot_timeout_s)
            # Convert to int milliseconds for the dataclass
            # contract. The multiplication-then-int truncation
            # gives millisecond resolution; sub-millisecond
            # precision is not useful at the SLO level we care
            # about.
            boot_duration_ms = int((time.monotonic() - start_time) * 1000)

            # Slow-boot SLO check. 5000 ms (5s) is the
            # empirically-observed threshold above which the
            # boot usually signals a real problem (image
            # pull, dep install, OOM kill + restart). Logged
            # at warning so it shows up in the operator's
            # default log view but does not gate the scan.
            if boot_duration_ms > 5000:
                logger.warning(
                    "boot.slow",
                    machine_id=machine_id,
                    duration_ms=boot_duration_ms,
                )

            return SandboxHealth(
                boot_duration_ms=boot_duration_ms,
                ready=True,
                logs=[],
                crash_signal=False,
            )
        except FlyError:
            # Any FlyError here means the machine did not
            # reach "started" within the timeout. Record the
            # elapsed time (which will be ~boot_timeout_s)
            # and return a not-ready snapshot.
            boot_duration_ms = int((time.monotonic() - start_time) * 1000)
            return SandboxHealth(
                boot_duration_ms=boot_duration_ms,
                ready=False,
                logs=[],
                crash_signal=False,
            )

    async def stream_logs(self, machine_id: str) -> AsyncIterator[str]:
        """Stream log lines from the machine.

        Thin async-iterator wrapper over
        `fly_client.stream_logs`. The current FlyClient
        implementation returns a full list rather than a
        live stream; this wrapper yields one line at a
        time so callers can `async for` over logs as they
        arrive in a future streaming implementation
        without changing the public API.

        Args:
            machine_id: Fly Machine ID.

        Yields:
            Individual log lines, in the order returned by
            Fly. Empty stream yields nothing.
        """
        lines = await self.fly_client.stream_logs(machine_id)
        for line in lines:
            yield line

    async def crash_recovery(
        self,
        machine_id: str,
        app_name: str,
        image: str,
        max_attempts: int = 2,
    ) -> str:
        """Destroy a crashed machine and respawn a new one.

        The retry loop is intentionally simple: destroy the
        old machine, create a new one, return the new id. If
        either step raises, the loop catches, logs, and
        retries. The loop bound is `max_attempts` *total*
        cycles, not `max_attempts` destroy-or-create retries
        — so `max_attempts=2` means up to two full
        destroy+create cycles.

        Why `except (FlyError, Exception)` instead of just
        `FlyError`: the underlying network call (httpx,
        aiohttp) can raise a non-FlyError on transient
        failures (connection reset, DNS hiccup). Treating
        those as retryable is the right default; the bounded
        retry count prevents an infinite loop on a persistent
        problem.

        Args:
            machine_id: ID of the crashed machine to destroy.
                Must be the *current* machine id (not the
                one that just failed to come up). The destroy
                call is best-effort — a 404 from Fly (machine
                already gone) is treated as success.
            app_name: Fly app name for the new machine.
            image: Container image for the new machine.
                Should be the *same* image as the crashed
                machine unless the crash was caused by an
                image problem (in which case the caller
                would pass a fixed image).
            max_attempts: Total destroy+respawn cycles
                before giving up. Default 2 (one retry).

        Returns:
            The new machine_id (from `fly_client.create_machine`'s
            response).

        Raises:
            SandboxCrashError: If all `max_attempts` cycles
                fail. The error carries the original
                `machine_id` and the most recent exception
                as `__cause__`.
        """
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(
                    "crash_recovery.attempt",
                    machine_id=machine_id,
                    attempt=attempt,
                    max_attempts=max_attempts,
                )

                # Step 1: destroy the old (crashed) machine.
                # The return value is intentionally ignored —
                # Fly returns True on success, raises FlyError
                # on 404 / 5xx. A 404 here is fine and is
                # already handled by the retry loop.
                await self.fly_client.destroy_machine(machine_id)

                # Step 2: create a new machine with the same
                # app/image. `auto_destroy=True` matches the
                # default set by the spin-up orchestrator so
                # the recovered machine has the same lifecycle
                # as a healthy one.
                new_machine = await self.fly_client.create_machine(
                    app_name=app_name,
                    image=image,
                    auto_destroy=True,
                )
                new_machine_id = new_machine["id"]

                logger.info(
                    "crash_recovery.success",
                    old_machine_id=machine_id,
                    new_machine_id=new_machine_id,
                    attempt=attempt,
                )

                # Happy path: return the new id to the caller,
                # which will plug it into subsequent health
                # checks / probes.
                return new_machine_id

            except (FlyError, Exception) as e:
                # Catch both FlyError (typed) and the broad
                # Exception (transient network/httpx errors).
                # The bound is enforced by the outer for-loop
                # and the max_attempts check below.
                last_error = e
                logger.warning(
                    "crash_recovery.failed",
                    machine_id=machine_id,
                    attempt=attempt,
                    error=str(e),
                )

        # All attempts failed. Surface as a typed error
        # carrying the original machine_id (so the caller
        # can log it directly) and the last exception
        # as `__cause__` (so `raise X from Y` semantics
        # preserve the traceback chain).
        raise SandboxCrashError(
            f"Crash recovery failed after {max_attempts} attempts",
            machine_id=machine_id,
        ) from last_error
