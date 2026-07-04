# Feature: No-stop Pivot Engine

**Purpose:** On 403/404 responses, pivot to adjacent resources/methods/params/tokens instead of quitting. 4-vector pivot strategy per Metis spec.
**Wave:** 4  **Owner task:** 25  **Status:** pending

## Public API
```python
class PivotEngine:
    def __init__(self, *, max_depth: int = 5, max_total: int = 200): ...
    def enqueue_pivots(self, blocked_route: RouteIndexEntry) -> list[RouteIndexEntry]:
        """Returns 1-20 pivot candidates based on 4-vector strategy."""
    def exhausted(self) -> bool: ...
```

## Internal flow (4 vectors on block)
1. **Adjacent paths deeper**: `/api/users/123` → `/api/users/123/admin`, `/api/users/123/settings`, `/api/users/123/billing`
2. **Method swap**: 403 on GET → try PATCH, DELETE, PUT, POST
3. **Token swap**: same path, swap User_A → User_B
4. **Parametric extension**: `?include=secrets`, `?debug=1`, `?fields=password_hash`

Stop conditions:
- Max depth 5 per origin path
- Total attempts cap 200 per scan
- LLM signals `exhausted_avenues: true` via dual-model orchestrator (Task 27)

## Inputs
- blocked_route: RouteIndexEntry
- attempt history (for dedup)

## Outputs
- list[RouteIndexEntry] (pivot candidates; enqueued to RouteWalker)

## Acceptance criteria
- [ ] 4-vector pivot strategy all emit on block
- [ ] Max-depth 5 enforced per origin
- [ ] Total attempts ≤ 200 per scan
- [ ] Pivot dedupes visited entries (no repeat probes)

## Test plan
```
Scenario: Blocked → pivots emitted
  Steps: enqueue_pivots(/api/users/123, blocked by GET 403)
  Expected: 1+ adjacent, 4 method swaps, 1+ param extensions
Scenario: Depth cap enforced
  Steps: 5-deep already; enqueue_pivots returns [] — capped
```

## Cross-references
- [see system-design.md#no-stop-pivot-spec]
- [see architecture.md#tier-pipeline-diagram]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |