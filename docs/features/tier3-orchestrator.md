# Feature: Tier 3 Orchestrator

**Purpose:** Chain Tier 3 modules — route walker + BOLA tester + pivot engine + dual-model + PoC sink → emit findings.
**Wave:** 4  **Owner task:** 29  **Status:** pending

## Public API
```python
@dataclass
class Tier3Result:
    scan_id: str
    findings: list[Finding]
    routes_walked: int
    blocked_pivots: int
    bola_attempts: int
    pocs: list[PoCCapture]
    cost: tuple[int, int, int]  # tokens_in, tokens_out, machine_seconds

class Tier3Orchestrator:
    async def run(self, *, scan_id: str, tier2_result: Tier2Result, budget: int = 200) -> Tier3Result: ...
```

## Internal flow
1. Receive Tier2Result (sandbox_handle, forged_tokens, route_index)
2. Instantiate RouteWalker over route_index
3. For each CurlProbe yielded by walker → execute via sandbox-svc → pass response to BolaTester
4. BolaTester emits BolaPoC OR null → if confirmed → PoCSink.capture
5. PivotEngine enqueues pivots on 403/404 (back to walker)
6. DualModelOrchestrator.iterate interleaves (every 5 probes, call OSS for next set)
7. Stop on budget exhausted OR PivotEngine.exhausted OR circuit-breaker
8. Destroy Machine via SandboxSpinup

## Inputs
- scan_id, Tier2Result, budget (default 200)

## Outputs
- Tier3Result containing findings, pocs, metrics

## Acceptance criteria
- [ ] Average Tier 3 walltime < 10min per scan
- [ ] BOLA confirmed + PoC captured on vuln fixture
- [ ] Machine destroyed post-scan
- [ ] Total spend <$0.50/scan (circuit-breaker enforced)

## Test plan
```
Scenario: Full Tier 3 chain on vuln fixture
  Steps: python -m sandbox.tier3 --scan-id ... --budget 200
  Expected: ≥1 finding returned; PoCs captured; cost <$0.50
Scenario: Circuit breaker
  Steps: --mock-cost-walls $0.45 already; iterate more
  Expected: terminates when cumulative cost hits $0.50 cap
```

## Cross-references
- [see architecture.md#tier-pipeline-diagram]
- [see system-design.md#no-stop-pivot-spec]
- [see billing-and-pricing.md#cost-per-scan-math]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |