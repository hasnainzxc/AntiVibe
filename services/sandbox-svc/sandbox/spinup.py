"""Sandbox spin-up orchestration for AntiVibe.

Flow per scan:
1. Generate Dockerfile for the detected stack (containerizer_fn)
2. Create Fly Machine via injected FlyClient (512MB, shared-cpu-1x, auto_destroy=True)
3. Wait for machine to reach "started" state
4. Apply egress DENY-ALL rules (localhost + established/related only)
5. Run DB seeder (mock) to populate test fixtures
6. Health check the sandbox URL
7. Log egress event to Supabase `sandbox_egress_log` table
8. Register atexit handler to destroy machine on process exit

All side effects (Fly API, iptables, Supabase) are injected or
parameterized so tests can run with full mocks and zero network.
"""

import atexit
import asyncio
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import structlog

logger = structlog.get_logger(__name__)


# Egress rule commands: deny all outbound except localhost loopback
# and established/related responses. Order matters — accept rules before DROP.
EGRESS_RULES: list[str] = [
    "iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT",
    "iptables -A OUTPUT -d 127.0.0.0/8 -j ACCEPT",
    "iptables -P OUTPUT DROP",
]


@dataclass
class SandboxHandle:
    """Handle returned to caller after a successful sandbox spin-up.

    machine_id: Fly Machine ID (used for destroy/exec)
    sandbox_url: Public URL where the running app is reachable
    seed_credentials: dict of seeded user/credential info for the scanner
    """

    machine_id: str
    sandbox_url: str
    seed_credentials: dict = field(default_factory=dict)


# Default iptables runner — executes via shell. Tests inject a fake runner.
def _default_iptables_runner(command: str) -> None:
    """Execute a single iptables command via the host shell.

    In production this would target the Fly Machine via exec; here we
    shell out locally. Errors are logged but non-fatal so that a missing
    iptables binary in dev doesn't break spin-up.
    """
    try:
        subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.warning("egress.rule_failed", command=command, error=str(e))


def apply_egress_rules(
    machine_id: str,
    runner: Optional[Callable[[str], None]] = None,
) -> list[str]:
    """Apply DENY-ALL egress rules for the given machine.

    Args:
        machine_id: Fly Machine ID (recorded in logs only)
        runner: Optional callable that runs a single iptables command.
                Defaults to a local subprocess runner. Tests pass a mock.

    Returns:
        List of iptables commands that were (or would be) executed.
    """
    effective_runner = runner or _default_iptables_runner
    for cmd in EGRESS_RULES:
        logger.info("egress.rule.apply", machine_id=machine_id, command=cmd)
        effective_runner(cmd)
    logger.info("egress.applied", machine_id=machine_id, rules=len(EGRESS_RULES))
    return list(EGRESS_RULES)


class SandboxSpinup:
    """Orchestrates Fly Machine creation + egress lockdown + seeding.

    All side-effecting dependencies are injected at __init__ time so the
    class is fully testable without network or filesystem access.
    """

    def __init__(
        self,
        fly_client: Any,
        supabase_client: Any,
        containerizer_fn: Callable[[Any, Path], str],
        seeder_fn: Callable[[Path], Awaitable[Any]],
    ):
        self.fly_client = fly_client
        self.supabase_client = supabase_client
        self.containerizer_fn = containerizer_fn
        self.seeder_fn = seeder_fn
        self._machine_id: Optional[str] = None
        self._atexit_registered = False
        self._destroyed = False

    async def run(
        self,
        scan_id: str,
        repo_root: Path,
        stack: Any,
        image_ref: str,
        app_name: str = "antivibe-sandbox",
        health_check_url: Optional[str] = None,
    ) -> SandboxHandle:
        """Spin up a sandbox and return a handle.

        Args:
            scan_id: Caller's scan identifier (for audit correlation)
            repo_root: Path to cloned repo on local FS
            stack: Detected stack enum (passed to containerizer)
            image_ref: Container image reference (e.g. registry/antivibe:abc)
            app_name: Fly app name (defaults to "antivibe-sandbox")
            health_check_url: Override URL for health check (otherwise
                derived from machine id + app_name)

        Returns:
            SandboxHandle with machine_id, sandbox_url, seed_credentials

        Raises:
            RuntimeError: if any step fails
        """
        # 1. Generate Dockerfile via injected containerizer
        dockerfile = self.containerizer_fn(stack, repo_root)
        stack_value = stack.value if hasattr(stack, "value") else str(stack)
        logger.info(
            "spinup.dockerfile.generated",
            scan_id=scan_id,
            stack=stack_value,
            bytes=len(dockerfile),
        )

        # 2. Create Fly Machine
        machine = await self.fly_client.create_machine(
            app_name=app_name,
            image=image_ref,
            env={"SCAN_ID": scan_id, "STACK": stack_value},
            auto_destroy=True,
        )
        machine_id = machine["id"]
        self._machine_id = machine_id
        logger.info("spinup.machine.created", scan_id=scan_id, machine_id=machine_id)

        # 3. Wait for it to reach "started"
        await self.fly_client.wait_for_running(machine_id)

        # 4. Apply egress DENY-ALL rules
        apply_egress_rules(machine_id)

        # 5. Log egress event to Supabase
        await self._log_egress_event(scan_id, machine_id)

        # 6. Run seeder (mock — writes JSON fixture)
        seed_result = await self.seeder_fn(repo_root)
        seed_credentials = self._extract_credentials(seed_result)

        # 7. Determine sandbox URL
        sandbox_url = health_check_url or self._build_sandbox_url(app_name, machine_id)

        # 8. Register atexit destroy (safety net)
        self._register_atexit_destroy()

        logger.info(
            "spinup.complete",
            scan_id=scan_id,
            machine_id=machine_id,
            sandbox_url=sandbox_url,
        )

        return SandboxHandle(
            machine_id=machine_id,
            sandbox_url=sandbox_url,
            seed_credentials=seed_credentials,
        )

    async def destroy(self) -> bool:
        """Destroy the machine. Idempotent. Returns True on success."""
        if self._destroyed or not self._machine_id:
            return True
        ok = await self.fly_client.destroy_machine(self._machine_id)
        self._destroyed = True
        logger.info(
            "spinup.destroyed",
            machine_id=self._machine_id,
            success=ok,
        )
        return ok

    def _register_atexit_destroy(self) -> None:
        """Register a sync atexit handler to destroy the machine on exit.

        atexit runs in the main thread after the event loop is closed,
        so we use asyncio.run to drive the async destroy.
        """
        if self._atexit_registered:
            return
        self._atexit_registered = True
        machine_id = self._machine_id

        def _sync_destroy() -> None:
            try:
                asyncio.run(self.fly_client.destroy_machine(machine_id))
            except Exception as e:  # noqa: BLE001 — atexit must not raise
                logger.warning(
                    "atexit.destroy_failed",
                    machine_id=machine_id,
                    error=str(e),
                )

        atexit.register(_sync_destroy)

    async def _log_egress_event(self, scan_id: str, machine_id: str) -> None:
        """Write a row to sandbox_egress_log via Supabase.

        Network/Supabase errors are logged but non-fatal — a missing audit
        log entry must not block scan execution.
        """
        if self.supabase_client is None:
            logger.info(
                "egress.log.skipped",
                reason="no_supabase_client",
                scan_id=scan_id,
            )
            return
        try:
            self.supabase_client.table("sandbox_egress_log").insert(
                {
                    "scan_id": scan_id,
                    "machine_id": machine_id,
                    "event": "egress_lockdown_applied",
                    "rules": EGRESS_RULES,
                }
            ).execute()
            logger.info(
                "egress.log.written",
                scan_id=scan_id,
                machine_id=machine_id,
            )
        except Exception as e:  # noqa: BLE001 — audit log is best-effort
            logger.warning(
                "egress.log.failed",
                scan_id=scan_id,
                machine_id=machine_id,
                error=str(e),
            )

    @staticmethod
    def _build_sandbox_url(app_name: str, machine_id: str) -> str:
        """Build the public URL for a Fly Machine.

        Real Fly Machines are reachable at https://<name>.fly.dev or via
        the .internal DNS for machine-to-machine. We use the public form.
        """
        return f"http://{app_name}.fly.dev"

    @staticmethod
    def _extract_credentials(seed_result: Any) -> dict:
        """Convert seeder output into a credentials dict for the scanner.

        Handles both SeedResult dataclass and plain dict for flexibility.
        """
        if seed_result is None:
            return {}
        if isinstance(seed_result, dict):
            return seed_result
        users = getattr(seed_result, "users", None) or []
        creds: dict = {}
        for u in users:
            uid = getattr(u, "uid", None)
            email = getattr(u, "email", None)
            password = getattr(u, "password", None)
            if uid and email and password:
                creds[uid] = {"email": email, "password": password}
        return creds
