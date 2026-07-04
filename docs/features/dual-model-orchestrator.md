# Feature: Dual-Model Orchestrator

**Purpose:** Coordinate commercial LLM (structural) + OSS hosted inference (fuzzing) on the scan path — extract via commercial, generate fuzz patterns via OSS, feed back.
**Wave:** 4  **Owner task:** 27  **Status:** pending

## Public API
```python
class DualModelOrchestrator:
    def __init__(self, *, extractor: LLMExtractor, fuzzer: OSSInferenceClient): ...
    async def iterate(self, *, route_map: list[RouteIndexEntry], sandbox_url: str, tokens: tuple[ForgedToken, ForgedToken], budget: int) -> AsyncIterator[Finding]: ...
```

## Internal flow
1. Tier1 (commercial) emits route_map → fwd to Tier3 iteration
2. Call OSSInferenceClient.generate(route_map, observed_responses=[], budget)
3. Receive list[FuzzPattern] → execute curls via sandbox
4. Collect responses → feed back to OSSInferenceClient → next batch
5. Call LLMExtractor (commercial) at saturation: summarize responses of confirmed BOLA → emit Finding
6. Stop conditions: exhausted_avenues (OSS signals) OR budget exhausted OR circuit-breaker
7. Cost ledger accumulates tokens from both models

## Inputs
- route_map (Tier1 + Tier2 RouteMapper)
- sandbox_url + forged_tokens (Tier2)
- budget

## Outputs
- AsyncIterator[Finding] streaming confirmed vulns (BOLA + pivoted ones)

## Acceptance criteria
- [ ] At least 1 confirmed finding on vuln fixture (BOLA) per test scan
- [ ] OSS inference consumed < 30K tokens per scan
- [ ] Commercial extractor < 50K tokens per scan
- [ ] Stop conditions enforced (no overrun)

## Test plan
```
Scenario: Confirms BOLA on fixture via dual-model loop
  Steps: iterate on fixture w/ seeded BOLA
  Expected: ≥1 Finding returned; cost <$0.50
Scenario: Exhausted_avenues signal stops loop
  Steps: stub OSS returns JSON w/ intent=null (exhausted)
  Expected: iteration terminates; no further curls issued
```

## Cross-references
- [see system-design.md#llm-dual-model-contract]
- [see architecture.md#cost-latency-guardrails]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |