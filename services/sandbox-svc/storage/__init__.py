"""Supabase Storage client for sandbox service.

Security boundary:
    Every call here uses the service-role key, which bypasses RLS and grants
    full read/write on every bucket. This module is therefore only safe inside
    the trusted server-side sandbox service. Never import it from a browser
    bundle, an edge function, or any context where the caller is untrusted.

Import graph:
    supabase.create_client — official supabase-py client; supabase-py returns
        an `UploadResponse` (object with `.error`) for upload/download/remove
        and a plain list for `list()`. We use `hasattr(result, "error")` to
        detect the error case uniformly across versions.

Bucket policy:
    Both buckets are PRIVATE. No public read URLs are issued; access is via
    short-lived signed URLs produced by the dashboard when the user is
    authenticated. The constants are exported but should not leak into client
    code (the dashboard re-declares them in TS to avoid this import).
"""

import os
from supabase import create_client, Client

BUCKET_SCAN_ARTIFACTS = "scan-artifacts"
BUCKET_POC_CAPTURES = "poc-captures"


def _get_service_client() -> Client:
    """Construct a fresh supabase-py client with the service-role key.

    A new client per call is intentional: supabase-py is not thread-safe across
    long-lived auth state, and the sandbox service is I/O bound on the network,
    not on client construction. The key is never cached on a module-level
    client because we want rotation to take effect on the next call.
    """
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def upload_scan_artifact(
    scan_id: str, kind: str, content: bytes,
    bucket: str = BUCKET_SCAN_ARTIFACTS
) -> str:
    """Upload an artifact under `{scan_id}/{kind}{ext}` and return the storage path.

    Uses `upsert=true` so re-running a scan (e.g. after a tier-2 retry) replaces
    the prior artifact without leaking orphan objects. The path layout is the
    contract the dashboard's `getScanArtifact` parses; do not change it without
    updating the TS counterpart.

    Raises:
        RuntimeError: supabase-py surfaced an error (network, RLS, quota).
    """
    client = _get_service_client()
    # `.` heuristic: callers pass either a logical name like `report` (gets `.json`)
    # or a fully-qualified filename like `capture.bin` (kept as-is). Saves every
    # call site from having to spell the extension.
    ext = "" if "." in kind else ".json"
    path = f"{scan_id}/{kind}{ext}"
    result = client.storage.from_(bucket).upload(path, content, {"upsert": "true"})
    # supabase-py returns UploadResponse; check for error
    if hasattr(result, "error") and result.error:
        raise RuntimeError(f"Storage upload failed: {result.error}")
    return path


def get_scan_artifact(
    scan_id: str, kind: str, bucket: str = BUCKET_SCAN_ARTIFACTS
) -> bytes:
    """Download an artifact and return its raw bytes.

    Caller is responsible for parsing (JSON vs binary). Mirror of
    `upload_scan_artifact` — same path convention.

    Raises:
        RuntimeError: missing object, RLS denial, or transport failure.
    """
    client = _get_service_client()
    ext = "" if "." in kind else ".json"
    path = f"{scan_id}/{kind}{ext}"
    result = client.storage.from_(bucket).download(path)
    if hasattr(result, "error") and result.error:
        raise RuntimeError(f"Storage download failed: {result.error}")
    return result


def delete_scan_artifacts(
    scan_id: str, bucket: str = BUCKET_SCAN_ARTIFACTS
) -> None:
    """Delete every artifact under `{scan_id}/`.

    Used when a scan is canceled or when its TTL expires. The list+remove pattern
    avoids a `list` with `limit=1000` truncation that would silently leave
    artifacts behind for very chatty scans.

    No-op if the folder is empty. Raises on transport or RLS error.
    """
    client = _get_service_client()
    files = client.storage.from_(bucket).list(scan_id)
    if files:
        paths = [f"{scan_id}/{f['name']}" for f in files]
        result = client.storage.from_(bucket).remove(paths)
        if hasattr(result, "error") and result.error:
            raise RuntimeError(f"Storage delete failed: {result.error}")
