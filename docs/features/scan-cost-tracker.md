# Feature: Scan Cost Tracker

**Purpose:** Accumulate Fly Machine seconds + LLM tokens → per-scan dollar ledger. Used by CircuitBreaker.
**Wave:** 6  **Owner task:** 40  **Status:** pending

## Public API
```python
class CostLedger:
    current_cents: int
    machine_seconds: int
    llm_tokens_in: int
    llm_tokens_out: int

    def add_machine_seconds(self, s: int) -> None: ...
    def add_llm_tokens(self, provider: str, tokens_in: int, tokens_out: int) -> None: ...
    def snapshot(self) -> ScanCosts: ...
```

## Internal flow
1. Cost per second Fly Machine: $0.00000444 (scraped from Fly pricing table Jan 2025; configurable env)
2. LLM costs from env: `ANTHROPIC_INPUT_COST_PER_1M_TOKENS`, `ANTHROPIC_OUTPUT_COST_PER_1M_TOKENS`, `TOGETHER_COST_PER_1M_TOKENS`
3. Integer cents to avoid float drift; round up to 1 cent floor
4. Called by FlyClient on each Machine create/destroy/log event; by LLMExtractor + OSSInferenceClient on each call

## Acceptance criteria
- [ ] Ledger adds correctly: 60s machine = ~0.027 cents; 50K tokens = ~$0.195 (together) or ~$0.75 (Anthropic)
- [ ] Snapshot matches scan result costs block

## Test plan
```
Scenario: 120s machine + 100K tokens = 27 cents
Scenario: Snapshot round-trip matches ScanCosts type
```

## Cross-references
- [see billing-and-pricing.md#cost-per-scan-math]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |