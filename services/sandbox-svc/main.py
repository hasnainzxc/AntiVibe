"""FastAPI entry point for the sandbox service.

Exposes an internal health endpoint for Fly.io load balancer checks.
"""

from fastapi import FastAPI

app = FastAPI(title="AntiVibe Sandbox Service", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
