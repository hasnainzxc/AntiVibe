# Feature: Sandbox Health Monitor

**Purpose:** Detect Machine boot completion, stream logs, recover from crashes, alert on cold-start >2s.
**Wave:** 3  **Owner task:** 21  **Status:** pending

## Public API
```python
@dataclass
class SandboxHealth:
    boot_duration_ms: int
    ready: bool
    logs: AsyncIterator[str]
    crash_signal: bool = False

class SandboxHealthMonitor:
    async def health(self, machine_id: str, *, boot_timeout_s: int = 120) -> SandboxHealth: ...
    async def stream_logs(self, machine_id: str) -> AsyncIterator[str]: ...
    async def crash_recovery(self, machine_id: str) -> str:
        """Destroy + respawn + return new machine_id."""
```

## Internal flow
1. Poll `fly_client.machine_health` every 1s; emit `machine.health.poll` structlog
2. On `status='started'` AND localhost port responds 200 → mark `ready=true`; capture `boot_duration_ms`
3. Stream logs via `fly_client.stream_logs` to structlog w/ scan_id tag
4. Heartbeat loss > 30s → mark `crash_signal=true`
5. On crash → `crash_recovery`: destroy + respawn (max 2 attempts; on 3rd fail → scan error=`machine_boot_failed`)
6. Boot time > 5s → emit `boot.slow` warning; if recurrent → suggest pre-warm pool (post-MVP)

## Inputs
- machine_id

## Outputs
- SandboxHealth record + log stream
- Crash-recovery escalation if needed

## Acceptance criteria
- [ ] Boot detection accurate < 2s across all fixture stacks
- [ ] Log stream forwarded to audit log (saved to blob storage as `agent-state.json` context)
- [ ] Crash recovery succeeds on 1 attempt on simulated crash (kill -9 in container)

## Test plan
```
Scenario: Boot detect
  Steps: spinup machine; health monitor returns ready=true + boot_duration_ms recorded
Scenario: Crash recovery
  Steps: kill -9 app process in machine; health detects crash; recovery respawn; new machine_id returned
```

## Cross-references
- [see sandbox-isolation.md#failure-modes--responses]
- [see ops-runbook.md#sandbox-hangs]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |