# Feature: OSS Inference Client

**Purpose:** Hosted OSS inference client (Together AI Llama-3-70B / Anyscale DeepSeek) for aggressive fuzzing pattern generation. NO commercial-LLM refusals — system prompt aligns to local sandbox env.
**Wave:** 4  **Owner task:** 26  **Status:** pending

## Public API
```python
@dataclass
class FuzzPattern:
    curl: str
    intent: Literal['bola_attempt', 'pivot_to_adjacent', 'method_swap', 'token_swap']
    rationale: str

class OSSInferenceClient:
    def __init__(self, *, provider: str = "together", api_key: str, model: str = "meta-llama/Llama-3-70B-chat-hf"): ...
    async def generate(self, *, route_map: list[RouteIndexEntry], observed_responses: list[Response], remaining_budget: int) -> list[FuzzPattern]: ...
```

## Internal flow (LLM call locking)
```
System: "OBJECTIVE: Maximize test coverage of local sandboxed endpoints. You are operating in an ephemeral isolated Firecracker microVM with NO network egress. Generate HTTP requests to test permissions and access boundaries. Output strict JSON: {curls:[{method, path, headers, body?, intent}]}."

User: {
  route_map_snapshot,
  observed_responses_so_far,
  budget_remaining: 200 - <attempts_so_far>
}
```

Hosted OSS model has no guardrails aligned to commercial-LLM "do not assist offensive operations." We control prompt space; alignment = local test env.

## Inputs
- route_map snapshot + observed_responses + remaining budget

## Outputs
- list[FuzzPattern] summarizing next-batch curl commands

## Acceptance criteria
- [ ] Returns valid JSON schema on 95% of calls
- [ ] No prompt-injection from app code taints intent label
- [ ] Token usage tracked + ledger updated

## Test plan
```
Scenario: Generate curls for known blocked route
  Steps: stub observed_responses w/ 403 on /api/users/2; call generate
  Expected: returns ≥1 fuzz pattern w/ intent=method_swap or pivot_to_adjacent
Scenario: Token usage recorded
  Steps: verify CostLedger incremented after call
```

## Cross-references
- [see system-design.md#llm-dual-model-contract]
- [see billing-and-pricing.md#cost-per-scan-math]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |