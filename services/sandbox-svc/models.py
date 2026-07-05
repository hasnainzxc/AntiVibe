
from pydantic import BaseModel


class ScanRequest(BaseModel):
    repo_url: str


class ScanResponse(BaseModel):
    scan_id: str
    status: str
    created_at: str


class ScanStatusResponse(BaseModel):
    id: str
    repo_url: str
    status: str
    created_at: str
    duration_ms: int | None = None
    total_findings: int | None = None
