"""Async Fly Machines REST API client with auto-destroy and structlog instrumentation."""

import os
import atexit
import asyncio
from typing import Optional
import httpx
import structlog

logger = structlog.get_logger(__name__)

FLY_API_BASE = "https://api.machines.dev"


class FlyError(Exception):
    """Typed Fly API error with machine_id context."""

    def __init__(self, message: str, machine_id: Optional[str] = None):
        super().__init__(message)
        self.machine_id = machine_id


class FlyClient:
    """Async client for Fly Machines REST API.

    Operations: create_machine, wait_for_running, stream_logs, destroy_machine,
    list_active_machines.
    All machines default to shared-cpu-1x, 512 MB RAM, 60 s lifecycle TTL.
    """

    def __init__(
        self, api_token: Optional[str] = None, base_url: str = FLY_API_BASE
    ):
        self.api_token = api_token or os.environ.get("FLY_API_TOKEN")
        if not self.api_token:
            raise FlyError("FLY_API_TOKEN is required")
        self.base_url = base_url
        self._destroy_queue: list[str] = []
        self._httpx_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
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
        client = await self._get_client()
        config: dict = {
            "image": image,
            "env": env or {},
            "size": "shared-cpu-1x",
            "memory_mb": 512,
            "auto_destroy": auto_destroy,
        }
        if cmd:
            config["init"] = {"cmd": cmd}

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
                self._destroy_queue.append(machine_id)
                atexit.register(self._cleanup)

            return machine
        except httpx.HTTPStatusError as e:
            raise FlyError(
                f"Fly API error: {e.response.status_code} {e.response.text}"
            )

    async def wait_for_running(
        self, machine_id: str, timeout: int = 120
    ) -> dict:
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
        client = await self._get_client()
        resp = await client.get(f"/v1/apps/machines/{machine_id}/logs")
        resp.raise_for_status()
        lines = resp.text.strip().split("\n") if resp.text else []
        logger.info("machine.logs", machine_id=machine_id, lines=len(lines))
        return lines

    async def destroy_machine(self, machine_id: str) -> bool:
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
            logger.warning(
                "machine.destroy_failed", machine_id=machine_id
            )
            return False

    async def list_active_machines(self) -> list[dict]:
        client = await self._get_client()
        resp = await client.get("/v1/apps/machines")
        resp.raise_for_status()
        return resp.json()

    async def _cleanup(self):
        for machine_id in list(self._destroy_queue):
            await self.destroy_machine(machine_id)

    async def close(self):
        await self._cleanup()
        if self._httpx_client:
            await self._httpx_client.aclose()
            self._httpx_client = None
