"""FastAPI entry point for the sandbox service.

Exposes:
  - GET  /health          Health check
  - POST /scan            Start a new scan
  - GET  /scan/{id}       Full scan details
  - GET  /scan/{id}/status  Scan status only
"""

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from models import ScanRequest
from scan_orchestrator import get_events, get_scan, get_scan_status, start_scan

app = FastAPI(title="AntiVibe Sandbox Service", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.post("/scan")
async def create_scan(req: ScanRequest):
    result = await start_scan(req.repo_url)
    if isinstance(result, tuple) and len(result) == 2:
        body, status_code = result
        return JSONResponse(content=body, status_code=status_code)
    return result


@app.get("/scan/{scan_id}/events")
async def read_scan_events(scan_id: str):
    return get_events(scan_id)


@app.get("/scan/{scan_id}")
async def read_scan(scan_id: str):
    result = await get_scan(scan_id)
    if result is None:
        return JSONResponse(content={"error": "Scan not found"}, status_code=404)
    return result


@app.get("/scan/{scan_id}/status")
async def read_scan_status(scan_id: str):
    result = await get_scan_status(scan_id)
    if result is None:
        return JSONResponse(content={"error": "Scan not found"}, status_code=404)
    return result
