# Feature: PoC Capture + Log Sink

**Purpose:** Save curl repro + response headers + status diff to blob storage + Supabase audit table for each confirmed finding.
**Wave:** 4  **Owner task:** 28  **Status:** pending

## Public API
```python
@dataclass
class PoCCapture:
    finding_id: str
    curl_repro: str
    actual_status: int
    response_headers: dict[str, str]
    response_excerpt: str  # first 1KB of body — secrets masked
    timestamp: str

class PoCSink:
    async def capture(self, *, scan_id: str, probe_request: CurlProbe, response: Response) -> PoCCapture: ...
    async def log_audit(self, *, scan_id: str, event: dict) -> None: ...
```

## Internal flow
1. Receive probe + response from BolaTester / Pivot
2. Mask secrets in response body via secret_detector (Task 12) `scan_string`
3. Construct `curl_repro` (invocation line w/ masked Authorization)
4. Save PoCCapture to Supabase Storage at `{scan_id}/poc/NN-curl.json`
5. Emit audit event to `sandbox_egress_log` if probe response indicates data exfil attempt (defense-in-depth)

## Inputs
- scan_id, probe_request, response

## Outputs
- PoCCapture record persisted to blob storage
- Structlog `poc.captured` event

## Acceptance criteria
- [ ] Every confirmed BOLA finding has 1 PoCCapture artifact w/ curl_repro reconstructable
- [ ] No raw Authorization in curl_repro (masked)
- [ ] PoC captured < 500ms

## Test plan
```
Scenario: Capture produced on BOLA confirm
  Steps: simulate User_A 200 OK on tenant2 resource; capture
  Expected: artifact saved; curl_repro is rerun-able in tox env; masked Authorization

Scenario: Secrets in response body masked
  Steps: response body w/ planted AWS key; capture
  Expected: artifact has __SECRET_TOKEN__ instead of AWS key
```

## Cross-references
- [see system-design.md#report-schema]
- [see security-threat-model.md#info-disclosure]
- [see blob-storage-client.md]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |