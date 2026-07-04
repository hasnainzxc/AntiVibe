# Feature: Fly Machines Client

**Purpose:** Async Python client wrapping Fly Machines REST API — create/destroy/wait/log/list. Auto-destroy on exit. Mockable via `respx`.
**Wave:** 1  **Owner task:** 5  **Status:** pending

## Public API
```python
# services/sandbox-svc/fly/client.py
class FlyClient:
    def __init__(self, api_token: str, *, cost_ledger: CostLedger | None = None): ...

    async def create_machine(
        self, image: str, *, env: dict[str, str], region: str | None = None,
        cmd: list[str] | None = None, size: str = "shared-cpu-1x",
        ram_mb: int = 512, disk_gb: int = 1, ttl_seconds: int = 60,
    ) -> FlyMachine: ...

    async def wait_for_running(self, machine_id: str, *, timeout_s: int = 120) -> bool: ...
    async def stream_logs(self, machine_id: str) -> AsyncIterator[str]: ...
    async def destroy_machine(self, machine_id: str, *, force: bool = True) -> None: ...
    async def list_active_machines(self) -> list[FlyMachine]: ...

@dataclass
class FlyMachine:
    id: str; app: str; region: str; image: str; created_at: datetime; status: str

class FlyError(Exception):
    def __init__(self, msg: str, *, machine_id: str | None = None): ...
```

## Internal flow
1. Async client via `httpx.AsyncClient`, base URL `https://api.machines.dev/v1`
2. Auth header: `Authorization: Bearer $FLY_API_TOKEN`
3. On `create_machine`: POST `/apps/{app}/machines`, register `atexit.register(self._destroy_at_exit, machine.id)` (last-ditch destroy)
4. On `wait_for_running`: poll GET `/apps/{app}/machines/{id}` every 1s until `status='started'` or timeout
5. On every call: emit structlog span w/ `machine.created`/`machine.destroyed`/`machine.timeout.invalidated` events, advance `CostLedger` if injected
6. Network failures wrap into `FlyError` w/ `machine_id` for tracing

## Inputs
- `FLY_API_TOKEN` env (fail-fast if missing)
- Image name (`antivibe/sandbox-base-py:<sha>` or user-app-built image)
- Region (random Fly default if None)

## Outputs
- `FlyMachine` records for upper layers to track
- Structlog JSON events to stdout

## Acceptance criteria
- [ ] `pytest services/sandbox-svc/tests/fly/test_client.py` passes 6 tests
- [ ] Coverage ≥ 90% for `fly/client.py`
- [ ] Abstract `FlyClient` exposed for test swap
- [ ] No sync handlers — async only
- [ ] Structlog JSON output (1 event per call)

## Test plan
```
Scenario: Destroy-after-create cycle via mock
  Steps: pytest services/sandbox-svc/tests/fly/test_client.py::test_lifecycle -v
  Expected: 1 create + 1 destroy in mock double
  Evidence: .omo/evidence/task-5-lifecycle.txt

Scenario: Token missing raises FlyError
  Steps: FLY_API_TOKEN= pytest -k test_no_token
  Expected: TypeError("FLY_API_TOKEN is required")
  Evidence: .omo/evidence/task-5-no-token.txt
```

## Cross-references
- [see architecture.md#component-inventory]
- [see sandbox-isolation.md#machine-specs]
- [see security-threat-model.md#elevation-of-privilege]
- [see ops-runbook.md#sandbox-hangs]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |