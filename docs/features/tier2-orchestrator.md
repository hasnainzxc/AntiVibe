# Feature: Tier 2 Orchestrator

**Purpose:** Chain Tier 2 modules: detect (already done in Tier 1) → containerize → seed → spin-up → forge JWT → handoff to Tier 3.
**Wave:** 3  **Owner task:** 22  **Status:** pending

## Public API
```python
@dataclass
class Tier2Result:
    scan_id: str
    sandbox_handle: SandboxHandle
    forged_tokens: tuple[ForgedToken, ForgedToken]
    route_index: list[RouteIndexEntry]
    auth_stack: AuthStack

class Tier2Orchestrator:
    async def run(self, *, scan_id: str, repo_root: Path, tier1_result: Tier1Result) -> Tier2Result: ...
```

## Internal flow
1. Re-use Tier1's `stack` + `auth_stack` detection
2. AppContainerizer → build image (Task 16)
3. SandboxSpinup → create + apply egress + wait for boot (Tasks 18, 21)
4. MockDBSeeder pre-seed (Task 17) inside the spun-up Machine
5. RouteMapper → build route index (Task 19)
6. JWTForge → mint 2 dummy users (Task 20)
7. Return SandboxHandle + tokens + route index → Tier 3 fuzz agent

## Inputs
- scan_id, repo_root, Tier1Result

## Outputs
- Tier2Result containing sandbox_handle, forged_tokens, route_index

## Acceptance criteria
- [ ] Tier 2 chain completes < 30s warm (< 90s cold)
- [ ] All Tier 3 inputs ready: sandbox reachable, tokens valid, routes indexed

## Test plan
```
Scenario: Full Tier 2 chain
  Steps: python -m sandbox.tier2 --scan-id ... ./fixtures/vuln/nextjs-firebase
  Expected: returns Tier2Result; tokens validate; sandbox returns 200 on /
```

## Cross-references
- [see architecture.md#tier-pipeline-diagram]
- [see system-design.md#sandbox-lifecycle]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |