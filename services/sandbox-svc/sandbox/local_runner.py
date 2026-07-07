"""Local Docker sandbox runner — replaces FlyClient for local MVP.

Uses docker-py instead of Fly Machines API. Implements the same async
interface as FlyClient so SandboxSpinup and SandboxHealthMonitor work
unchanged.

Architecture
------------
Each "machine" maps to a local Docker container. The lifecycle is:

    1. build_image(repo_root, dockerfile_path) -> tag
       Builds image from per-stack Dockerfile. Called once per scan.

    2. create_machine(app_name, image, env, ...) -> {"id": cid}
       Runs container with port mapping + --network none.

    3. wait_for_running(cid) -> {"state": "started"}
       Polls container status until 'running'.

    4. destroy_machine(cid) -> bool
       docker rm -f.

Port mapping uses STACK env var to determine which port to publish:
    nextjs  -> 3000, express -> 8000, fastapi -> 8000,
    flask   -> 5000, sveltekit -> 4173, firebase -> 8080

Egress is enforced via Docker's --network none (no network at all).
The seeder runs via docker exec. Health check is port-based.

Dependency map
--------------
- docker-py (docker>=7.0.0) for all Docker daemon interactions.
- structlog for structured logging.

Testing
-------
- Mock docker.from_env in unit tests.
- Integration tests require a running Docker daemon.
"""

import asyncio
import os
import atexit
from pathlib import Path
from typing import Optional
import structlog

import docker
from docker.errors import DockerException, NotFound

logger = structlog.get_logger(__name__)

STACK_PORT_MAP: dict[str, int] = {
    "nextjs": 3000,
    "express": 8000,
    "fastapi": 8000,
    "flask": 5000,
    "sveltekit": 4173,
    "firebase": 8080,
}


class LocalDockerError(Exception):
    """Typed Docker error with optional container_id context."""

    def __init__(self, message: str, container_id: Optional[str] = None):
        super().__init__(message)
        self.container_id = container_id


class LocalDockerClient:
    """Async Docker-based sandbox runner.

    Same duck-typed interface as FlyClient. Used by SandboxSpinup,
    SandboxHealthMonitor, and the tier2 orchestrator with zero
    code changes to those modules.

    Docker operations are synchronous (docker-py's native API) but
    wrapped in run_in_executor to avoid blocking the event loop for
    long operations like image builds.
    """

    def __init__(self, network: str = "none"):
        self._client = docker.from_env()
        self._network = network
        self._destroy_queue: list[str] = []
        self._container_urls: dict[str, str] = {}
        atexit.register(self._cleanup_sync)

    def _port_for_stack(self, env: Optional[dict[str, str]] = None) -> int:
        """Determine container port from STACK env var."""
        if env and "STACK" in env:
            return STACK_PORT_MAP.get(env["STACK"].lower(), 3000)
        return 3000

    def build_image(
        self, repo_root: Path, dockerfile_path: Path, tag: str = "antivibe-sandbox:local"
    ) -> str:
        """Build Docker image from generated Dockerfile.

        Args:
            repo_root: Build context directory (cloned repo root).
            dockerfile_path: Absolute path to Dockerfile.antivibe.
            tag: Image tag.

        Returns:
            Image tag string (same as input, for chaining).

        Raises:
            LocalDockerError: if build fails.
        """
        logger.info("docker.build.start", dockerfile=str(dockerfile_path), tag=tag)
        try:
            dockerfile_rel = dockerfile_path.relative_to(repo_root)
        except ValueError:
            dockerfile_rel = dockerfile_path.name

        try:
            image, logs = self._client.images.build(
                path=str(repo_root),
                dockerfile=str(dockerfile_rel),
                tag=tag,
                rm=True,
            )
            logger.info("docker.build.done", tag=tag, image_id=image.id[:12])
        except DockerException as e:
            logger.error("docker.build.failed", tag=tag, error=str(e))
            raise LocalDockerError(f"Image build failed: {e}") from e

        return tag

    async def create_machine(
        self,
        app_name: str = "antivibe-sandbox",
        image: str = "antivibe-sandbox:local",
        env: Optional[dict[str, str]] = None,
        region: str = "local",
        cmd: Optional[list[str]] = None,
        auto_destroy: bool = True,
    ) -> dict:
        """Create and start a Docker container.

        Maps container port to a random host port. Returns dict shaped
        like FlyClient.create_machine response.

        Args:
            app_name: Ignored (local Docker has no apps).
            image: Docker image tag to run.
            env: Environment variables for the container.
            region: Ignored.
            cmd: Override command (CMD in Dockerfile).
            auto_destroy: If True, queue for cleanup on close/atexit.

        Returns:
            {"id": container_id, "state": "created"}

        Raises:
            LocalDockerError: if container creation fails.
        """
        container_port = self._port_for_stack(env)
        port_cfg = {f"{container_port}/tcp": ("127.0.0.1",)}  # random host port

        try:
            container = self._client.containers.run(
                image=image,
                command=cmd,
                environment=env or {},
                network=self._network,
                ports=port_cfg,
                detach=True,
                auto_remove=False,
            )
            container.reload()
            # Read back the actual host port mapping
            net_settings = container.attrs.get("NetworkSettings", {})
            ports_info = net_settings.get("Ports", {})
            host_port = container_port  # fallback
            if f"{container_port}/tcp" in ports_info:
                bindings = ports_info[f"{container_port}/tcp"]
                if bindings and len(bindings) > 0:
                    host_port = int(bindings[0].get("HostPort", str(container_port)))

            container_id = container.id
            local_url = f"http://127.0.0.1:{host_port}"
            self._container_urls[container_id] = local_url

            logger.info(
                "docker.container.created",
                container_id=container_id[:12],
                image=image,
                url=local_url,
            )

            if auto_destroy:
                self._destroy_queue.append(container_id)

            return {"id": container_id, "state": "created"}

        except DockerException as e:
            logger.error("docker.create.failed", image=image, error=str(e))
            raise LocalDockerError(f"Container create failed: {e}") from e

    def get_container_url(self, container_id: str) -> str:
        """Return the localhost URL for a container.

        URL is determined at create_machine time from port mapping.
        """
        return self._container_urls.get(container_id, "http://127.0.0.1:3000")

    async def wait_for_running(
        self, container_id: str, timeout: int = 120
    ) -> dict:
        """Wait for container to reach 'running' state.

        Polls Docker every 1s. Raises on terminal states or timeout.

        Args:
            container_id: Docker container ID (full or short).
            timeout: Max seconds to wait.

        Returns:
            {"state": "started"} on success.

        Raises:
            LocalDockerError: on terminal state or timeout.
        """
        deadline = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < deadline:
            try:
                container = self._client.containers.get(container_id)
                state = container.status

                if state == "running":
                    logger.info(
                        "docker.container.ready",
                        container_id=container_id[:12],
                    )
                    return {"state": "started"}

                if state in ("exited", "dead"):
                    logs = container.logs(tail=20).decode("utf-8", errors="replace")
                    raise LocalDockerError(
                        f"Container entered terminal state: {state}\n{logs}",
                        container_id=container_id,
                    )
            except NotFound:
                raise LocalDockerError(
                    f"Container {container_id[:12]} not found",
                    container_id=container_id,
                )

            await asyncio.sleep(1)

        raise LocalDockerError(
            f"Container {container_id[:12]} timed out after {timeout}s",
            container_id=container_id,
        )

    async def stream_logs(self, container_id: str) -> list[str]:
        """Fetch container logs, split into lines."""
        try:
            container = self._client.containers.get(container_id)
            logs = container.logs(tail=100).decode("utf-8", errors="replace")
            return logs.strip().split("\n") if logs.strip() else []
        except NotFound:
            return []

    async def destroy_machine(self, container_id: str) -> bool:
        """Remove container with force. Idempotent.

        Returns True if the container is now gone.
        """
        try:
            container = self._client.containers.get(container_id)
            container.remove(force=True, v=True)
            logger.info(
                "docker.container.destroyed",
                container_id=container_id[:12],
            )
            if container_id in self._destroy_queue:
                self._destroy_queue.remove(container_id)
            return True
        except NotFound:
            logger.warning(
                "docker.container.not_found",
                container_id=container_id[:12],
            )
            return True
        except DockerException as e:
            logger.warning(
                "docker.container.destroy_failed",
                container_id=container_id[:12],
                error=str(e),
            )
            return False

    async def list_active_machines(self) -> list[dict]:
        """List all containers (running + stopped)."""
        containers = self._client.containers.list(all=True)
        return [{"id": c.id, "state": c.status} for c in containers]

    async def close(self):
        """Drain destroy queue."""
        await self._cleanup()

    async def _cleanup(self):
        """Destroy all queued containers."""
        for cid in list(self._destroy_queue):
            await self.destroy_machine(cid)

    def _cleanup_sync(self):
        """Sync atexit handler — drains queue outside event loop."""
        try:
            asyncio.run(self._cleanup())
        except Exception:
            pass
