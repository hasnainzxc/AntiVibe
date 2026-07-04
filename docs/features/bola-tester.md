# Feature: BOLA / IDOR Tester

**Purpose:** Cross-tenant Broken Object Level Authorization tester — swap URL params (tenant IDs) + swap forged tokens to detect access-control gaps.
**Wave:** 4  **Owner task:** 24  **Status:** pending

## Public API
```python
@dataclass
class BolaProbe:
    target_path: str               # e.g. /api/users/2 (tenant2 id w/ tenant1 token)
    user_token: ForgedToken
    intent: Literal['id_swap', 'token_swap', 'cross_tenant']
    expected_status: int           # 403 (correct) or 200 (vuln)

@dataclass
class BolaPoC:
    target_path: str
    curl_repro: str
    actual_status: int
    user_a_rejected_correctly: bool

class BolaTester:
    async def test_route(self, route: RouteIndexEntry, *, sandbox_url: str, forged_tokens: tuple[ForgedToken, ForgedToken]) -> BolaPoC | None: ...
```

## Internal flow
1. Receive route w/ `:id` param from walker (Task 23)
2. Issue User_A token + tenant1 id path → check baseline (should 200 if owner)
3. Issue User_A token + tenant2 id path → expect 403; if 200 → BOLA confirmed
4. Issue User_B token + tenant1 id path → symmetrical test
5. Capture curl_repro + actual_status + reject_flag (oracle check)
6. On confirmed BOLA: emit BolaPoC w/ curl_repro for upstream PoC log sink (Task 28)

## Inputs
- route_index (Task 19)
- forged_tokens (Task 20)
- sandbox_url (Task 18)

## Outputs
- list[BolaPoC] — one per confirmed BOLA detection

## Acceptance criteria
- [ ] Detects seeded BOLA on fixture `vuln/nextjs-firebase` (User_A can read tenant2 univ)
- [ ] Returns null/false for fixture `clean/nextjs-firebase` (no BOLA)
- [ ] curl_repro captures method, headers (w/ token masked), path

## Test plan
```
Scenario: BOLA detected on vuln fixture
  Steps: test_route on fixture /api/users/:id where :id=2, User_A token
  Expected: 200 → BolaPoC returned; curl_repro captured
Scenario: No BOLA on clean fixture
  Steps: same path/method/tokens on clean fixture
  Expected: 403 → no BolaPoC returned
```

## Cross-references
- [see system-design.md#no-stop-pivot-spec]
- [see system-design.md#report-schema]
- [see security-threat-model.md#elevation-of-privilege]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |