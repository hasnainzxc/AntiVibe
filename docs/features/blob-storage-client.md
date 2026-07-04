# Feature: Blob Storage Client

**Purpose:** Server-side Supabase Storage client for private scan artifacts + PoC captures. Server-only; never ship anon-key uploads.
**Wave:** 1  **Owner task:** 6  **Status:** pending

## Public API
```ts
// apps/dashboard/lib/storage/client.ts (TS, server-side)
export async function uploadScanArtifact(scan_id: string, kind: string, bytes: Buffer | string): Promise<string> // url
export async function getScanArtifact(scan_id: string, kind: string): Promise<Buffer>
export async function signedUploadURL(scan_id: string, kind: string): Promise<{ url: string; path: string }>
export async function deleteScanArtifacts(scan_id: string): Promise<void>
```

```python
# services/sandbox-svc/storage/__init__.py
async def upload_scan_artifact(scan_id: str, kind: str, data: bytes) -> str: ...  # url
async def get_scan_artifact(scan_id: str, kind: str) -> bytes: ...
async def delete_scan_artifacts(scan_id: str) -> None: ...
```

## Internal flow
1. Auth via Supabase service-role key (server only)
2. Bucket: `scan-artifacts` (private), `poc-captures` (private)
3. Path layout: `{scan_id}/{kind}.{ext}` (e.g., `123e/report.json`, `456e/poc/01-curl.json`)
4. TS client uses `@supabase/supabase-js` server client
5. Python client uses `supabase-py` server client
6. Both wraps network errors to typed `StorageError`

## Inputs
- scan_id (uuid)
- kind (string enum: `report.json`, `poc/N-curl.json`, `egress-log.json`, `agent-state.json`)
- bytes

## Outputs
- Signed URL valid for ~60min (configurable)
- Stored object in Supabase Storage private bucket

## Acceptance criteria
- [ ] TS + Python round-trip 1KB blob; SHA256 matches
- [ ] Bucket metadata `public = false`
- [ ] Anon key without auth GET returns 4xx

## Test plan
```
Scenario: Roundtrip upload+download integrity
  Steps: python -m sandbox.storage --roundtrip test-bytes-$(date +%s)
  Expected: SHA256 uploaded == downloaded; 200
  Evidence: .omo/evidence/task-6-roundtrip.txt

Scenario: Anon denied upload to private bucket
  Steps: curl -X POST "$SUPABASE_URL/storage/v1/object/scan-artifacts/x.txt" -H "Authorization: Bearer $ANON"
  Expected: 4xx
  Evidence: .omo/evidence/task-6-anon-disabled.txt
```

## Cross-references
- [see architecture.md#component-inventory]
- [see api-spec.md#get-apiscanidreport]
- [see security-threat-model.md#info-disclosure]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |