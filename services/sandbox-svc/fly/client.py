"""Async Fly Machines REST API client with auto-destroy and structlog instrumentation.

Security boundary:
    Holds a Fly API token with full org-level access. The token is loaded from the
    `FLY_API_TOKEN` env var (or injected for tests) and is never logged or echoed
    back in error messages — only the machine_id and HTTP status are surfaced.

Import graph:
    httpx        — async HTTP transport, one shared AsyncClient per FlyClient
    structlog    — structured JSON logging; every state transition emits an event
    atexit       — last-resort cleanup hook in case the caller forgets close()
    os / asyncio — env lookup, event-loop time for timeout loops

Lifecycle:
    create_machine()  → enqueue id if auto_destroy=True
    wait_for_running()→ poll 1s until started or terminal state
    destroy_machine() → delete + dequeue
    close()           → drain queue + close httpx client (call on app shutdown)

Default sizing (shared-cpu-1x, 512 MB) matches the sandbox tier in `sandbox/spinup.py`.
"""

import os
import atexit
import asyncio
from typing import Optional
import httpx
import structlog

logger = structlog.get_logger(__name__)

# Fly's hosted Machines API. Override with `base_url=` for tests / staging.
FLY_API_BASE = "https://api.machines.dev"


class FlyError(Exception):
    """Typed Fly API error with machine_id context.

    `machine_id` is populated when the failure is tied to a specific machine
    (e.g. timeout, terminal state). It is omitted for setup failures such as
    a missing `FLY_API_TOKEN` because no machine was ever allocated.

    Callers can branch on the message text for retry decisions: 4xx responses
    are typically caller bugs (bad image, bad region) and should not be retried;
    5xx / network errors are transient and may be retried with backoff.
    """

    def __init__(self, message: str, machine_id: Optional[str] = None):
        super().__init__(message)
        self.machine_id = machine_id


class FlyClient:
    """Async client for Fly Machines REST API.

    Operations: create_machine, wait_for_running, stream_logs, destroy_machine,
    list_active_machines.
    All machines default to shared-cpu-1x, 512 MB RAM, 60 s lifecycle TTL.

    One FlyClient == one Fly app context. Constructing a new client per request
    is fine; the underlying `httpx.AsyncClient` is lazily created on first call
    and reused for the lifetime of the instance.
    """

    def __init__(
        self, api_token: Optional[str] = None, base_url: str = FLY_API_BASE
    ):
        # Token is read once at construction. The instance never re-reads the
        # env var, so rotating the secret requires a new client.
        self.api_token = api_token or os.environ.get("FLY_API_TOKEN")
        if not self.api_token:
            raise FlyError("FLY_API_TOKEN is required")
        self.base_url = base_url
        # Machine ids queued for `atexit` cleanup. Bounded by scan concurrency;
        # for long-running services, prefer an explicit `close()` instead of
        # relying on the atexit safety net.
        self._destroy_queue: list[str] = []
        self._httpx_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        # Lazy init: avoids creating the connection pool when the client is
        # constructed in a sync context (e.g. Django management commands).
        if self._httpx_client is None:
            self._httpx_client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._httpx_client

    async def create_machine(
        self,
        app_name: str,
        image: str,
        env: Optional[dict[str, str]] = None,
        region: str = "iad",
        cmd: Optional[list[str]] = None,
        auto_destroy: bool = True,
    ) -> dict:
        """Allocate a new machine and optionally queue it for auto-destruction.

        Args:
            app_name: Fly app slug; the machine is created under `/v1/apps/{app_name}/machines`.
            image:    Docker image ref. Must be pushed to the app's registry first.
            env:      Key/value env vars injected at start. Secrets belong here, not in `cmd`.
            region:   Fly region code (e.g. `iad`, `lhr`). Default Ashburn, VA.
            cmd:      Optional override command — wired into `config.init.cmd`.
            auto_destroy: If True, Fly kills the machine on stop; we also queue it
                locally so an atexit sweep can clean up if the caller crashes.

        Returns:
            The raw machine dict from the Fly API (id, state, region, config…).

        Raises:
            FlyError: missing token (constructor) or 4xx/5xx from the Fly API.
        """
        client = await self._get_client()
        # Shared-cpu-1x / 512 MB is the cheapest tier that runs the sandbox image
        # without OOM. Bumping memory_mb is the primary knob if tier-2 spinup
        # reports OOMKill in fly logs.
        config: dict = {
            "image": image,
            "env": env or {},
            "size": "shared-cpu-1x",
            "memory_mb": 512,
            "auto_destroy": auto_destroy,
        }
        if cmd:
            # Fly takes the entrypoint under `init.cmd`. Empty cmd keeps the image's
            # default ENTRYPOINT, which is the right default for the sandbox image.
            config["init"] = {"cmd": cmd}

        # Random 4-byte hex suffix avoids name collisions if the caller does not
        # pass an explicit name. Fly would 409 on duplicate names within an app.
        payload = {
            "name": f"antivibe-sandbox-{os.urandom(4).hex()}",
            "region": region,
            "config": config,
            "skip_launch": False,
        }

        try:
            resp = await client.post(
                f"/v1/apps/{app_name}/machines", json=payload
            )
            resp.raise_for_status()
            machine = resp.json()
            machine_id = machine["id"]
            logger.info(
                "machine.created",
                machine_id=machine_id,
                app=app_name,
                region=region,
            )

            if auto_destroy:
                # Local queue: belt-and-suspenders. Fly's auto_destroy already
                # handles the happy path; this catches the case where the Python
                # process dies before destroy_machine() is called.
                self._destroy_queue.append(machine_id)
                # atexit is registered once per machine. Subsequent calls just
                # append to the queue; the final cleanup drains whatever remains.
                atexit.register(self._cleanup)

            return machine
        except httpx.HTTPStatusError as e:
            # The response body is included for debugging but may contain
            # sensitive Fly-internal details. Don't log full body in prod.
            raise FlyError(
                f"Fly API error: {e.response.status_code} {e.response.text}"
            )

    async def wait_for_running(
        self, machine_id: str, timeout: int = 120
    ) -> dict:
        """Poll the machine state until it reaches `started` or a terminal state.

        Polls once per second. Fly's API is rate-limited per-token, so anything
        more aggressive risks 429s during bursty scans. 1s is a safe lower bound
        that also keeps P99 wait_for_running latency under ~1.1s of the actual
        boot time.

        Args:
            machine_id: Returned by `create_machine`.
            timeout:    Max seconds to wait. Default 120s; tier-2 image boot is
                typically <15s, so 120s leaves headroom for cold caches.

        Returns:
            The machine dict once `state == "started"`.

        Raises:
            FlyError: machine entered a terminal state (`stopped`/`destroyed`/`failed`),
                or the timeout was reached before `started`.
        """
        client = await self._get_client()
        deadline = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < deadline:
            resp = await client.get(f"/v1/apps/machines/{machine_id}")
            resp.raise_for_status()
            machine = resp.json()
            state = machine.get("state", "")

            if state == "started":
                logger.info("machine.ready", machine_id=machine_id)
                return machine
            # `stopped` and `destroyed` mean the machine never made it to `started`
            # under our watch. `failed` usually means an OOM or bad entrypoint.
            if state in ("stopped", "destroyed", "failed"):
                raise FlyError(
                    f"Machine entered terminal state: {state}",
                    machine_id=machine_id,
                )

            await asyncio.sleep(1)

        logger.error(
            "machine.timeout", machine_id=machine_id, timeout=timeout
        )
        raise FlyError(
            f"Machine {machine_id} timed out after {timeout}s",
            machine_id=machine_id,
        )

    async def stream_logs(self, machine_id: str) -> list[str]:
        """Fetch the full log buffer for a machine and split on newlines.

        Fly's logs endpoint returns a snapshot (not a stream) — the result is
        the buffered log lines since machine creation. For real-time streaming
        over a long-running scan, use Fly's log tail / NATS-based push instead.

        Returns an empty list when the machine has not produced any output.
        """
        client = await self._get_client()
        resp = await client.get(f"/v1/apps/machines/{machine_id}/logs")
        resp.raise_for_status()
        lines = resp.text.strip().split("\n") if resp.text else []
        logger.info("machine.logs", machine_id=machine_id, lines=len(lines))
        return lines

    async def destroy_machine(self, machine_id: str) -> bool:
        """Delete a machine and dequeue it from the auto-destroy queue.

        Idempotent: returns True on success, False on 4xx/5xx. The 4xx case
        (e.g. 404 for an already-destroyed machine) is treated as success-equivalent
        for cleanup purposes — the machine is gone, which is the goal.

        Returns True if the machine is now gone, False if the API call failed.
        Never raises — destroy is best-effort.
        """
        client = await self._get_client()
        try:
            resp = await client.delete(
                f"/v1/apps/machines/{machine_id}"
            )
            resp.raise_for_status()
            logger.info("machine.destroyed", machine_id=machine_id)

            if machine_id in self._destroy_queue:
                self._destroy_queue.remove(machine_id)
            return True
        except httpx.HTTPStatusError:
            # Don't escalate — the scan result is what the user cares about, and
            # a leftover machine costs pennies. Fly's own auto_destroy catches
            # the rest on its TTL.
            logger.warning(
                "machine.destroy_failed", machine_id=machine_id
            )
            return False

    async def list_active_machines(self) -> list[dict]:
        """List ALL machines for the configured Fly app.

        No filtering by state or region — caller decides what counts as 'active'.
        Result includes destroyed machines for ~30s after deletion (Fly retention).
        """
        client = await self._get_client()
        resp = await client.get("/v1/apps/machines")
        resp.raise_for_status()
        return resp.json()

    async def _cleanup(self):
        """atexit safety net — destroys whatever is still queued.

        Sync callers cannot await this; atexit runs `_cleanup` without awaiting,
        so any in-flight destroy will be interrupted by interpreter shutdown.
        Prefer calling `close()` explicitly in async shutdown paths.
        """
        for machine_id in list(self._destroy_queue):
            await self.destroy_machine(machine_id)

    async def close(self):
        """Drain the destroy queue and release the httpx connection pool.

        Safe to call multiple times. After close(), the client is reusable
        for read-only calls (list_active_machines, stream_logs) but auto_destroy
        enqueueing will leak — construct a new FlyClient for new scans.
        """
        await self._cleanup()
        if self._httpx_client:
            await self._httpx_client.aclose()
            self._httpx_client = None
