# Feature: E2E Scan Integration Service

**Purpose:** Orchestrate end-to-end scan from URL intake → run all 3 tiers → produce report → auto-PR → email. One call from dashboard.
**Wave:** 6  **Owner task:** 43  **Status:** pending

## Public API
```python
class ScanIntegrationService:
    async def run_full_scan(self, *, scan_id: str, repo_url: str, full_scan: bool = True) -> ScanResult: ...
```

## Internal flow
1. Call Tier 1 orchestrator (Task 15)
2. Call Tier 2 orchestrator (Task 22) if `full_scan`
3. Call Tier 3 orchestrator (Task 29)if `full_scan` and Tier 2 succeeded
4. Call ReportGenerator (Task 31) on normalized findings
5. Call AutoPRWriter (Task 33) for each remediation-ready finding
6. Call ScanEmailDelivery (Task 42) to notify user
7. Update scans.status to `done`/`partial`/`failed`

## Acceptance criteria
- [ ] End-to-end throughput < 12min on typical vuln fixture
- [ ] All 3 tiers + report + auto-PR chain works on vuln fixture
- [ ] Circuit-breaker honored during chain

## Test plan
```
Scenario: Full 3-tier journey
  Steps: curl -X POST /api/scan -F repo=...; poll until status=done
  Expected: report JSON + PR URL in scan record
```

## Cross-references
- [see architecture.md#tier-pipeline-diagram]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |