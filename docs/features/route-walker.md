# Feature: Route Walker

**Purpose:** Stateful walker over route index emitting curl probes. Maintains queue, dedupes visited, respects attempt cap (200/scan).
**Wave:** 4  **Owner task:** 23  **Status:** pending

## Public API
```python
class RouteWalker:
    def __init__(self, *, route_index: list[RouteIndexEntry], forged_tokens: tuple[ForgedToken, ForgedToken], max_attempts: int = 200): ...
    def __aiter__(self) -> AsyncIterator[CurlProbe]: ...
    def mark_blocked(self, entry: RouteIndexEntry, reason: str) -> None: ...
    def verdict(self) -> WalkerState: ...
```

## Internal flow
1. BFS frontier over routes w/ `RouteIndexEntry` queue
2. For each route, yield curl probe variants: tokenless, User_A token, User_B token
3. Consumption loop: receive response → mark entry visited → record route state → fetch next from queue
4. Respect attempt cap (200 per scan) + depth cap (5 levels per origin path)
5. On `mark_blocked`, route skipped from primary queue; pivot engine (Task 25) may re-enqueue adjacent

## Inputs
- route_index (Task 19)
- forged_tokens (Task 20)

## Outputs
- Async stream of `CurlProbe` payloads for orchestrator

## Acceptance criteria
- [ ] Visit count ≤ 200 per scan
- [ ] All routes from fixture visited at least once (unblocked subset)
- [ ] Async iterator yields ≤ 10ms between probes

## Test plan
```
Scenario: Bounded visits
  Steps: walker over fixture w/ 250 routes → emits exactly 200
Scenario: Token variant dedup
  Steps: route visited w/ User_A token; route w/ admin token variant dedupes (same path+method)
```

## Cross-references
- [see system-design.md#no-stop-pivot-spec]
- [see architecture.md#cost-latency-guardrails]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |