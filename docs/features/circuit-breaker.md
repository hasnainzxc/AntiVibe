# Feature: Circuit Breaker

**Purpose:** Kill scan if $0.50 cap exceeded OR 10min elapsed. Write partial report. Refund quota.
**Wave:** 6  **Owner task:** 41  **Status:** pending

## Public API
```python
class CircuitBreaker:
    def __init__(self, *, max_cost_cents: int = 50, max_runtime_s: int = 600, ledger: CostLedger): ...
    def check(self) -> bool:   # True = safe to continue; False = circuit tripped
    def trip_reason(self) -> str | None: ...  # "cost_cap" | "timeout" | None
```

## Internal flow
1. `check()` called at each significant computational boundary (clone, LLM call, route walk step, etc.)
2. Compares `ledger.current_cents` vs 50; `started_at - now` vs 600
3. On trip: write partial report via Tier1/Tier3 result so far; mark scan `status=partial`; refund quota if user paid free tier scan
4. Kill all in-flight async tasks via `asyncio.CancelledError` propagation + destroy Machine

## Acceptance criteria
- [ ] Trips at $0.50 cost or 600s walltime
- [ ] Writes partial + logs trip reason

## Test plan
```
Scenario: $0.50 cap trips + partial report
  Steps: mock cost > 0.50; check() returns False; trip reason=cost_cap
Scenario: 11min timeout trips
  Steps: move clock; check() returns False; trip reason=timeout
```

## Cross-references
- [see architecture.md#cost--latency-guardrails]
- [see ops-runbook.md#sandbox-runaway-cost]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |