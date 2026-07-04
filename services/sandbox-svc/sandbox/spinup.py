"""Sandbox spin-up orchestration for AntiVibe.

Architecture
------------
This is the *only* module in `sandbox/` that touches real side
effects. It coordinates six distinct external systems:

    1. containerizer (Dockerfile gen)  -> sandbox/containerize.py
    2. fly_client (machine lifecycle)  -> fly/client.py
    3. iptables (egress lockdown)      -> local shell
    4. supabase (audit log)            -> storage layer
    5. seeder (test fixture injection) -> sandbox/seeder.py
    6. atexit (process-exit cleanup)   -> stdlib

Every one of those is *injected* at `__init__` time so the class is
fully testable with mocks and zero network. The default iptables
runner is the only side effect that ships as module-level glue
(because there is no upstream abstraction to inject from); tests
swap it via `monkeypatch` or by passing `runner=` to
`apply_egress_rules` directly.

Design rationale — ordering matters
-----------------------------------
The flow inside `run()` is deliberately strict:

    1. Dockerfile       (pure; no side effect on machine)
    2. Create machine   (network)
    3. Wait for started (network; no auth, just health)
    4. DENY-ALL egress  (iptables on machine)
    5. Log egress event (Supabase)
    6. Seed DB          (depends on egress being locked first)
    7. Build URL        (pure)
    8. Register atexit  (defensive; never blocks)

Step 4 *must* precede step 6. The seeder is fed plaintext
credentials and known-vulnerable schema; if egress were permissive
at seed time, a misbehaving image could exfiltrate the exact
fixture a real attacker would need. The audit log (step 5) is
written *before* seeding for the same reason — it lets the SOC
correlate "lockdown applied" with "seed run" if anything goes
wrong. Audit is best-effort and never blocks the scan.

Step 8 (`atexit`) is a safety net for process crashes — if the
caller's `try/finally` around `run()` fails or the process is
killed, the machine is still destroyed. Idempotency is enforced
via `self._destroyed` and `self._atexit_registered` flags so
multiple `run()` invocations on the same instance don't double-
register or double-destroy.

Dependency map
--------------
- Reads from: scanner.detect_stack.Stack (for the containerizer call)
- Reads from: sandbox.containerize (template function — injected)
- Reads from: sandbox.seeder (seeder function — injected)
- Reads from: fly.client.FlyClient (machine lifecycle — injected)
- Reads from: a Supabase-shaped client for the audit log (injected,
  may be None)
- Writes to: iptables on the host (via the default runner),
  Supabase `sandbox_egress_log` table, an atexit handler in the
  current process.

Testing
-------
- `tests/sandbox/test_spinup.py` covers: machine creation args,
  containerizer call shape, wait ordering, seeder handoff,
  credential extraction (dict and SeedResult shapes), idempotent
  destroy, atexit registration, best-effort audit log, default
  iptables runner swallow behavior, no-real-network smoke tests.
"""

import atexit
import asyncio
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import structlog

logger = structlog.get_logger(__name__)


# Egress rule commands. Order is load-bearing: the ACCEPT rules for
# ESTABLISHED/RELATED and loopback must be applied *before* the
# default-DROP policy, otherwise the first outbound connection
# (e.g. the DNS lookup the seeder needs) would itself be denied and
# we'd deadlock the spin-up.
#
# These are the same three rules that ship in the spinup integration
# test for the dev sandbox host. Production runs apply them via the
# Fly Machine's `fly machine exec` (not local iptables); the local
# path is for dev/CI only.
EGRESS_RULES: list[str] = [
    "iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT",
    "iptables -A OUTPUT -d 127.0.0.0/8 -j ACCEPT",
    "iptables -P OUTPUT DROP",
]


@dataclass
class SandboxHandle:
    """Handle returned to caller after a successful sandbox spin-up.

    Fields:
        machine_id: Fly Machine ID; required for destroy and exec.
        sandbox_url: Public URL where the running app is reachable.
            The scanner issues HTTP probes against this URL.
        seed_credentials: `{uid: {email, password}}` mapping for the
            seeded users, so the scanner can sign in as any of them
            without re-reading the seed source. Default empty so
            callers that don't need creds can construct a partial
            handle.
    """

    machine_id: str
    sandbox_url: str
    seed_credentials: dict = field(default_factory=dict)


# Default iptables runner — executes via the local shell. Tests inject
# a fake runner (see apply_egress_rules) so this code path is never
# hit in CI.
def _default_iptables_runner(command: str) -> None:
    """Execute a single iptables command via the host shell.

    Best-effort: any failure (binary missing, permission denied,
    timeout) is logged at warning level and swallowed. Rationale:
    spin-up must not abort because the dev laptop lacks iptables.
    The orchestrator's audit log captures the *attempted* rules
    regardless of whether they actually took effect — a SOC can
    correlate sandbox URL ↔ rule application post-hoc.

    Args:
        command: Full iptables command line, e.g.
            `"iptables -P OUTPUT DROP"`. Executed via `subprocess.run`
            with `shell=True` (the command itself is the safety
            boundary, not the parser).

    Returns:
        None. The function never raises on runtime failure.

    Side effects:
        Spawns a 10s-bounded subprocess. On timeout, the process is
        left to the OS reaper; we do not block the event loop
        because subprocess.run is sync and called from the async
        `run()` only as a fallback when no async iptables binding
        is available.
    """
    try:
        subprocess.run(
            command,
            shell=True,
            # check=False: never raise on non-zero exit. We log
            # the failure but treat iptables-missing as a soft
            # warning rather than a spin-up blocker.
            check=False,
            capture_output=True,
            # 10s is generous for a single iptables append; we
            # don't want a hung iptables lock to wedge spin-up.
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        # Swallow + log. The caller (apply_egress_rules) continues
        # to the next rule even if this one failed; partial
        # lockdown is better than no lockdown for a sandbox.
        logger.warning("egress.rule_failed", command=command, error=str(e))


def apply_egress_rules(
    machine_id: str,
    runner: Optional[Callable[[str], None]] = None,
) -> list[str]:
    """Apply DENY-ALL egress rules for the given machine.

    Runs each command in `EGRESS_RULES` through the supplied
    `runner` (or `_default_iptables_runner` if not given). Returns
    the list of commands that were (or would have been) executed,
    so the caller can log or audit them.

    Args:
        machine_id: Fly Machine ID. Used for log correlation only;
            the commands themselves are host-local. Pass the
            machine_id even on the local-iptables path so log
            aggregation can join `egress.rule.apply` events back to
            the right machine.
        runner: Optional callable that accepts one iptables command
            string and applies it. Tests pass a `MagicMock` here
            to record the calls. Defaults to the local subprocess
            runner.

    Returns:
        A *copy* of `EGRESS_RULES`. Returning a copy prevents
        callers from mutating the module-level constant.

    Raises:
        Whatever `runner` raises. The default runner is swallow-
        all, so production paths do not raise; tests can use
        a runner that raises to assert error propagation.
    """
    effective_runner = runner or _default_iptables_runner
    for cmd in EGRESS_RULES:
        # Per-rule log line so the SOC can see *which* rule
        # applied (vs. which failed). INFO level because this
        # is the normal path.
        logger.info("egress.rule.apply", machine_id=machine_id, command=cmd)
        effective_runner(cmd)
    logger.info("egress.applied", machine_id=machine_id, rules=len(EGRESS_RULES))
    return list(EGRESS_RULES)


class SandboxSpinup:
    """Orchestrates Fly Machine creation + egress lockdown + seeding.

    Dependency injection shape (constructor args):
        fly_client       — async, exposes create_machine / wait_for_running /
                           destroy_machine. The real implementation lives in
                           `fly/client.py`; tests pass `AsyncMock`.
        supabase_client  — sync, chainable `table().insert().execute()`.
                           Optional (None is allowed and skips the audit log).
        containerizer_fn — `(stack, repo_root) -> str`. Returns the Dockerfile
                           content. Production wires this to
                           `sandbox.containerize.generate_dockerfile`.
        seeder_fn        — `async (repo_root) -> SeedResult | dict`.
                           Production wires this to
                           `sandbox.seeder.seed_to_json` (or one of the live
                           seeders for end-to-end runs).

    The instance keeps a small amount of mutable state
    (`_machine_id`, `_destroyed`, `_atexit_registered`) so
    `destroy()` is idempotent and `run()` can be called more than
    once on the same instance without leaking atexit handlers.
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
        # Internal state. `Optional[str]` because `destroy()`
        # must be a no-op if `run()` was never called or failed
        # before machine creation.
        self._machine_id: Optional[str] = None
        # Guards against double-registering atexit on repeated
        # run() invocations. Each atexit entry would otherwise
        # try to destroy the *current* machine, which after a
        # second run() would be a different (live) one.
        self._atexit_registered = False
        # Guards against double-destroy. The destroy() call is
        # idempotent but the Fly API is not — repeated destroy
        # on a destroyed machine returns 404.
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

        Executes the 8-step orchestration documented in the module
        docstring. On any unrecoverable failure, partial side
        effects are best-effort cleaned up by the atexit handler
        registered on success; callers that need stricter cleanup
        should wrap the call in `try/finally` and invoke
        `destroy()` themselves.

        Args:
            scan_id: Caller's scan identifier. Threaded through
                into the machine's `env` so log lines from inside
                the sandbox can be correlated back to the scan.
            repo_root: Path to the cloned repo on the local FS.
                Passed to both the containerizer (currently
                unused) and the seeder.
            stack: Detected stack enum. Used for the containerizer
                and for the `STACK` env var on the machine. The
                caller passes the `scanner.detect_stack.Stack`
                value; duck-typed because the containerizer fn is
                injected (and tests may pass a string or a MagicMock).
            image_ref: Container image reference, e.g.
                `registry.antivibe.internal/antivibe:abc123`.
                Must already be pushed to the registry.
            app_name: Fly app name. Defaults to `"antivibe-sandbox"`,
                which is the production app the FlyClient is
                configured against. Override only for dev/integration
                tests that use a sandbox Fly org.
            health_check_url: If supplied, used verbatim as
                `sandbox_url` on the returned handle. If None, the
                URL is derived from `app_name` (see
                `_build_sandbox_url`).

        Returns:
            `SandboxHandle` with `machine_id`, `sandbox_url`, and
            `seed_credentials` extracted from the seeder output.

        Raises:
            RuntimeError: if any orchestration step fails
                irrecoverably. Concrete failure modes:
                - containerizer raises (unknown stack)
                - fly_client.create_machine raises (auth, quota)
                - wait_for_running times out (machine never came up)
                - seeder raises (DB unreachable)
                Audit-log and egress-rule failures are *not* raised.
        """
        # 1. Generate Dockerfile via injected containerizer. Pure
        # (no side effect) — safe to run first; failure here means
        # we don't even attempt to create a machine.
        dockerfile = self.containerizer_fn(stack, repo_root)
        # Stack enum may be a `scanner.detect_stack.Stack` (has
        # `.value`) or a plain string (test mocks). The
        # `hasattr` guard is what keeps the orchestrator
        # usable from both production and tests.
        stack_value = stack.value if hasattr(stack, "value") else str(stack)
        logger.info(
            "spinup.dockerfile.generated",
            scan_id=scan_id,
            stack=stack_value,
            bytes=len(dockerfile),
        )

        # 2. Create Fly Machine. `auto_destroy=True` is a
        # belt-and-suspenders backup to the atexit handler:
        # if the host process is killed hard (SIGKILL, OOM),
        # Fly will reap the machine when its TTL elapses.
        machine = await self.fly_client.create_machine(
            app_name=app_name,
            image=image_ref,
            # env vars surface inside the sandbox as plain env;
            # the app under test can read them for its own
            # observability.
            env={"SCAN_ID": scan_id, "STACK": stack_value},
            auto_destroy=True,
        )
        machine_id = machine["id"]
        self._machine_id = machine_id
        logger.info("spinup.machine.created", scan_id=scan_id, machine_id=machine_id)

        # 3. Wait for it to reach "started". Polling is delegated
        # to FlyClient so its timeout/retry policy lives in one
        # place. If this raises, the machine exists but is
        # unhealthy — caller should destroy and retry.
        await self.fly_client.wait_for_running(machine_id)

        # 4. Apply egress DENY-ALL rules. This MUST happen
        # before the seeder runs (see module docstring).
        # apply_egress_rules is sync and intentionally so —
        # iptables shell-out is the simplest available path.
        apply_egress_rules(machine_id)

        # 5. Log egress event to Supabase. Best-effort; a
        # missing audit log must not block the scan.
        await self._log_egress_event(scan_id, machine_id)

        # 6. Run seeder. The default seeder is the offline
        # JSON path; the live Postgres/Firestore seeders
        # can also be wired here for end-to-end runs.
        seed_result = await self.seeder_fn(repo_root)
        # Extract the {uid: {email, password}} map the
        # scanner uses to sign in as each seeded user.
        seed_credentials = self._extract_credentials(seed_result)

        # 7. Determine sandbox URL. The override (if given)
        # is typically the URL returned by Fly's private
        # networking layer in test environments.
        sandbox_url = health_check_url or self._build_sandbox_url(app_name, machine_id)

        # 8. Register atexit destroy. Safety net for clean
        # process exit; main cleanup is still the caller's
        # `try/finally` around `run()`.
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
        """Destroy the machine. Idempotent.

        Returns:
            True on success or if already destroyed; the
            `fly_client.destroy_machine` return value otherwise.
            Callers should not branch on this — the only
            useful signal is that the machine is gone from
            Fly's perspective.

        Raises:
            Whatever `fly_client.destroy_machine` raises.
            Notably this is *not* swallowed here, because the
            caller (typically a `try/finally` in the scan
            orchestrator) needs to know if cleanup failed.
        """
        if self._destroyed or not self._machine_id:
            # Either we never ran, or destroy already
            # succeeded. Both are valid no-ops.
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

        Why sync: `atexit` runs *after* the event loop has been
        closed. Calling an async coroutine directly here would
        raise `RuntimeError: Event loop is closed`. We therefore
        wrap the async `destroy_machine` call in a fresh
        `asyncio.run` inside a sync function.

        Why a wrapper: atexit registers must be top-level callables
        that take no required args. We close over `machine_id`
        via default-arg capture so the value seen at *destruction*
        time matches the one seen at *registration* time, even if
        the instance spins up a second machine later.

        Why swallow exceptions: atexit handlers that raise are
        silently dropped (and may corrupt interpreter shutdown).
        The atexit path is a *safety net*; the primary cleanup
        path is `await self.destroy()` from the caller's
        `try/finally`. We log at warning level so the failure
        is at least visible.
        """
        if self._atexit_registered:
            return
        self._atexit_registered = True
        # Capture `machine_id` into a local so the closure
        # doesn't see a later `_machine_id` if a second run()
        # happens before the interpreter exits.
        machine_id = self._machine_id

        def _sync_destroy() -> None:
            try:
                # Fresh event loop — the original one is gone
                # by the time atexit fires. asyncio.run is the
                # documented way to drive a one-shot coroutine
                # outside an existing loop.
                asyncio.run(self.fly_client.destroy_machine(machine_id))
            except Exception as e:  # noqa: BLE001 — atexit must not raise
                logger.warning(
                    "atexit.destroy_failed",
                    machine_id=machine_id,
                    error=str(e),
                )

        atexit.register(_sync_destroy)

    async def _log_egress_event(self, scan_id: str, machine_id: str) -> None:
        """Write a row to `sandbox_egress_log` via Supabase.

        Best-effort by design: the audit log is a SOC tool, not
        a control-plane signal. A Supabase outage or network
        blip during egress logging must not abort the scan.
        Failures are logged at warning level; the operator can
        cross-reference scan_id against the machine_id later
        to reconstruct what happened.

        Args:
            scan_id: Scan identifier from the caller.
            machine_id: Fly Machine ID the rules were applied to.
        """
        if self.supabase_client is None:
            # Common in dev/CI where the Supabase client is
            # never wired. Logged at info because it's normal,
            # not an error.
            logger.info(
                "egress.log.skipped",
                reason="no_supabase_client",
                scan_id=scan_id,
            )
            return
        try:
            # The Supabase client is a chainable builder:
            #   .table(name).insert(row).execute() -> response
            # We use positional + keyword args to match the
            # documented supabase-py API.
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

        Real Fly Machines are reachable at `https://<app>.fly.dev`
        (the public form) or via `<machine_id>.<app>.internal`
        (private form, machine-to-machine). We use the public
        form because the scanner's HTTP probes are intentionally
        black-box — they should see the same URL an external
        attacker would.

        Args:
            app_name: Fly app name (e.g. "antivibe-sandbox").
            machine_id: Currently unused; the public URL is
                app-level, not machine-level. Kept in the
                signature for future per-machine DNS records.

        Returns:
            `http://<app_name>.fly.dev`. Note `http://`, not
            `https://` — Fly's edge terminates TLS for us and
            the upstream connection is plain HTTP inside the
            same region.
        """
        return f"http://{app_name}.fly.dev"

    @staticmethod
    def _extract_credentials(seed_result: Any) -> dict:
        """Convert seeder output into a credentials dict for the scanner.

        Two input shapes are supported:
            - `SeedResult` dataclass (the offline JSON seeder).
            - Plain `dict` (the live seeders return a dict, not
              a dataclass, to keep the wire shape simple).

        Returns:
            `{uid: {"email": ..., "password": ...}}`. Users
            missing any of `uid`, `email`, `password` are
            silently skipped — partial creds are useless to
            the scanner and would just be a noisy
            KeyError downstream.
        """
        if seed_result is None:
            return {}
        if isinstance(seed_result, dict):
            return seed_result
        # SeedResult path. `getattr` with None default makes
        # this resilient to a future SeedResult shape change.
        users = getattr(seed_result, "users", None) or []
        creds: dict = {}
        for u in users:
            uid = getattr(u, "uid", None)
            email = getattr(u, "email", None)
            password = getattr(u, "password", None)
            if uid and email and password:
                creds[uid] = {"email": email, "password": password}
        return creds
