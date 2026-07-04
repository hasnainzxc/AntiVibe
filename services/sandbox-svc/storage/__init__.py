"""Supabase Storage client for sandbox service."""

import os
from supabase import create_client, Client

BUCKET_SCAN_ARTIFACTS = "scan-artifacts"
BUCKET_POC_CAPTURES = "poc-captures"


def _get_service_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def upload_scan_artifact(scan_id: str, kind: str, content: bytes, bucket: str = BUCKET_SCAN_ARTIFACTS) -> str:
    client = _get_service_client()
    ext = "" if "." in kind else ".json"
    path = f"{scan_id}/{kind}{ext}"
    result = client.storage.from_(bucket).upload(path, content, {"upsert": "true"})
    # supabase-py returns UploadResponse; check for error
    if hasattr(result, "error") and result.error:
        raise RuntimeError(f"Storage upload failed: {result.error}")
    return path


def get_scan_artifact(scan_id: str, kind: str, bucket: str = BUCKET_SCAN_ARTIFACTS) -> bytes:
    client = _get_service_client()
    ext = "" if "." in kind else ".json"
    path = f"{scan_id}/{kind}{ext}"
    result = client.storage.from_(bucket).download(path)
    if hasattr(result, "error") and result.error:
        raise RuntimeError(f"Storage download failed: {result.error}")
    return result


def delete_scan_artifacts(scan_id: str, bucket: str = BUCKET_SCAN_ARTIFACTS) -> None:
    client = _get_service_client()
    files = client.storage.from_(bucket).list(scan_id)
    if files:
        paths = [f"{scan_id}/{f['name']}" for f in files]
        result = client.storage.from_(bucket).remove(paths)
        if hasattr(result, "error") and result.error:
            raise RuntimeError(f"Storage delete failed: {result.error}")
