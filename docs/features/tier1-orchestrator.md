# Feature: Tier 1 Orchestrator

**Purpose:** Async chain practical order — clone → detect → AST → parallel analyzers (secret + config + LLM) → merge findings → write intermediary JSON to blob storage.
**Wave:** 2  **Owner task:** 15  **Status:** pending

## Public API
```python
@dataclass
class Tier1Result:
    scan_id: str
    findings: list[Finding]
    route_map: list[RouteShape]
    env_refs: list[EnvRef]
    imports: dict[str, DependencyRef]
    status: Literal['done', 'partial']
    costs: tuple[int, int]  # tokens in/out

class Tier1Orchestrator:
    def __init__(self, *, fly_client, sb_client, storage_client, llm_extractor, ...): ...
    async def run(self, *, scan_id: str, repo_url: str) -> Tier1Result: ...
```

## Internal flow
1. `clone_repo` (Task 9)
2. `detect_stack` (Task 10)
3. `AstParser.extract_routes` + `find_env_refs` + `extract_imports` (Task 11)
4. Parallel via `asyncio.gather`:
   - `secret_detector.scan_tree` (Task 12)
   - `config_flaw_analyzer.analyze` (Task 13)
   - `llm_extractor.analyze` (Task 14)
5. Merge findings dedup (line+title key)
6. Write `tier1_output.json` to blob storage at `{scan_id}/tier1_output.json`
7. Circuit-breaker: walltime > 60s → abort remaining LLM calls, write partial, status=partial

## Inputs
- scan_id
- repo_url

## Outputs
- Tier1Result dict for upstream caller (Tier 2/Tier 3)
- Intermediary JSON blob in Supabase Storage

## Acceptance criteria
- [ ] Takes fixture repo path → returns merged findings
- [ ] Circuit-breaker fires at 60s walltime, produces partial output
- [ ] One finding per issue (no dups across analyzers)

## Test plan
```
Scenario: Full chain on vuln fixture
  Steps: python -m scanner.tier1 ./fixtures/vuln/nextjs-firebase
  Expected: ≥1 secret + ≥1 firestore-rule + ≥1 LLM finding; status=done
Scenario: Slow LLM → partial output
  Steps: --mock-llm-delay=70s
  Expected: status=partial_tier1; LLM findings skipped w/ reason=timeout
```

## Cross-references
- [see architecture.md#tier-pipeline-diagram]
- [see system-design.md#llm-dual-model-contract]
- [see sandbox-isolation.md#audit-log]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |