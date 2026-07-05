"""Tests for scan orchestrator."""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock


class MockSupabase:
    def __init__(self):
        self.data = []
        self._update_data = {}

    def table(self, name):
        return self

    def insert(self, data):
        self.data.append(data)
        return self

    def update(self, data):
        self._update_data = data
        return self

    def eq(self, field, value):
        return self

    def select(self, fields="*"):
        return self

    def execute(self):
        return MagicMock(data=self.data)


class MockTier2Result:
    def __init__(self, status="complete", routes=None, error=None):
        self.status = status
        self.routes = routes or []
        self.error = error


def make_route(path="/api/test", methods=None, auth_required=False):
    return type("RouteEntry", (), {
        "path": path,
        "methods": methods or ["GET"],
        "auth_required": auth_required,
        "auth_stack": "custom",
        "file_path": "",
        "line": 0,
    })()


class TestStartScan:
    @pytest.mark.asyncio
    async def test_invalid_url_returns_400(self):
        from scan_orchestrator import start_scan
        result = await start_scan("not-a-url")
        assert isinstance(result, tuple)
        assert result[1] == 400
        assert "Invalid" in result[0]["error"]

    @pytest.mark.asyncio
    async def test_valid_url_returns_scan_id(self, monkeypatch):
        mock_sb = MockSupabase()
        mock_sb.data = [{"id": "test-id"}]

        def mock_get_sb(*args, **kwargs):
            return mock_sb
        monkeypatch.setattr("scan_orchestrator.get_supabase_client", mock_get_sb)

        # Prevent background task from actually running
        monkeypatch.setattr("scan_orchestrator.asyncio.create_task", lambda c: None)

        from scan_orchestrator import start_scan
        result = await start_scan("https://github.com/user/repo")
        assert isinstance(result, dict)
        assert "scan_id" in result
        assert result["status"] == "queued"
        assert mock_sb.data[-1]["repo_url"] == "https://github.com/user/repo"
        assert mock_sb.data[-1]["status"] == "queued"


class TestRunPipeline:
    @pytest.mark.asyncio
    async def test_full_scan_success(self, monkeypatch):
        mock_sb = MockSupabase()
        mock_sb.data = [{"id": "test-scan-id"}]

        def mock_get_sb(*args, **kwargs):
            return mock_sb
        monkeypatch.setattr("scan_orchestrator.get_supabase_client", mock_get_sb)

        async def mock_tier1(url, **kw):
            return {
                "status": "complete",
                "stack": "nextjs",
                "repo": "/tmp/mock-repo",
                "findings": [
                    {"source": "secret_detector", "severity": "high", "title": "Test finding"}
                ],
            }
        monkeypatch.setattr("scan_orchestrator.run_tier1", mock_tier1)

        async def mock_tier2(**kw):
            return MockTier2Result(
                status="complete",
                routes=[make_route("/api/data", ["GET"], auth_required=True)],
            )
        monkeypatch.setattr("scan_orchestrator.run_tier2", mock_tier2)

        from scan_orchestrator import _run_pipeline
        await _run_pipeline("test-scan-id", "https://github.com/user/repo", mock_sb)

        assert mock_sb._update_data.get("status") == "completed"
        assert mock_sb._update_data.get("total_findings") == 2

    @pytest.mark.asyncio
    async def test_tier2_graceful_degradation(self, monkeypatch):
        mock_sb = MockSupabase()
        mock_sb.data = [{"id": "test-scan-id"}]

        def mock_get_sb(*args, **kwargs):
            return mock_sb
        monkeypatch.setattr("scan_orchestrator.get_supabase_client", mock_get_sb)

        async def mock_tier1(url, **kw):
            return {
                "status": "complete",
                "stack": "nextjs",
                "repo": "/tmp/mock-repo",
                "findings": [
                    {"source": "secret_detector", "severity": "high", "title": "Test finding"}
                ],
            }
        monkeypatch.setattr("scan_orchestrator.run_tier1", mock_tier1)

        async def mock_tier2(**kw):
            raise RuntimeError("Tier 2 crashed")
        monkeypatch.setattr("scan_orchestrator.run_tier2", mock_tier2)

        from scan_orchestrator import _run_pipeline
        await _run_pipeline("test-scan-id", "https://github.com/user/repo", mock_sb)

        assert mock_sb._update_data.get("status") == "completed"
        assert mock_sb._update_data.get("total_findings") == 1

    @pytest.mark.asyncio
    async def test_tier1_error_marks_scan_failed(self, monkeypatch):
        mock_sb = MockSupabase()
        mock_sb.data = [{"id": "test-scan-id"}]

        def mock_get_sb(*args, **kwargs):
            return mock_sb
        monkeypatch.setattr("scan_orchestrator.get_supabase_client", mock_get_sb)

        async def mock_tier1(url, **kw):
            return {"status": "error", "error": "Clone failed: repo not found"}
        monkeypatch.setattr("scan_orchestrator.run_tier1", mock_tier1)

        from scan_orchestrator import _run_pipeline
        await _run_pipeline("test-scan-id", "https://github.com/bad/repo", mock_sb)

        assert mock_sb._update_data.get("status") == "failed"

    @pytest.mark.asyncio
    async def test_skips_tier2_for_non_nextjs_express(self, monkeypatch):
        mock_sb = MockSupabase()
        mock_sb.data = [{"id": "test-scan-id"}]

        def mock_get_sb(*args, **kwargs):
            return mock_sb
        monkeypatch.setattr("scan_orchestrator.get_supabase_client", mock_get_sb)

        async def mock_tier1(url, **kw):
            return {
                "status": "complete",
                "stack": "fastapi",
                "repo": "/tmp/mock-repo",
                "findings": [],
            }
        monkeypatch.setattr("scan_orchestrator.run_tier1", mock_tier1)
        tier2_called = False

        async def mock_tier2(**kw):
            nonlocal tier2_called
            tier2_called = True
            return MockTier2Result()
        monkeypatch.setattr("scan_orchestrator.run_tier2", mock_tier2)

        from scan_orchestrator import _run_pipeline
        await _run_pipeline("test-scan-id", "https://github.com/user/repo", mock_sb)

        assert not tier2_called
        assert mock_sb._update_data.get("status") == "completed"


class TestGetScan:
    @pytest.mark.asyncio
    async def test_get_scan_returns_none_for_missing(self, monkeypatch):
        mock_sb = MockSupabase()
        mock_sb.data = []

        def mock_get_sb(*args, **kwargs):
            return mock_sb
        monkeypatch.setattr("scan_orchestrator.get_supabase_client", mock_get_sb)

        from scan_orchestrator import get_scan
        result = await get_scan("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_scan_parses_json_findings(self, monkeypatch):
        mock_sb = MockSupabase()
        mock_sb.data = [{
            "id": "scan-1",
            "repo_url": "https://github.com/user/repo",
            "status": "completed",
            "created_at": "2025-01-01T00:00:00",
            "tier1_findings": json.dumps([{"source": "secret_detector"}]),
            "tier2_findings": None,
        }]

        def mock_get_sb(*args, **kwargs):
            return mock_sb
        monkeypatch.setattr("scan_orchestrator.get_supabase_client", mock_get_sb)

        from scan_orchestrator import get_scan
        result = await get_scan("scan-1")
        assert result is not None
        assert result["status"] == "completed"
        assert len(result["tier1_findings"]) == 1
        assert result["tier1_findings"][0]["source"] == "secret_detector"


class TestGetScanStatus:
    @pytest.mark.asyncio
    async def test_get_status_returns_only_status_fields(self, monkeypatch):
        mock_sb = MockSupabase()
        mock_sb.data = [{
            "id": "scan-1",
            "repo_url": "https://github.com/user/repo",
            "status": "tier1",
            "created_at": "2025-01-01T00:00:00",
        }]

        def mock_get_sb(*args, **kwargs):
            return mock_sb
        monkeypatch.setattr("scan_orchestrator.get_supabase_client", mock_get_sb)

        from scan_orchestrator import get_scan_status
        result = await get_scan_status("scan-1")
        assert result is not None
        assert result["status"] == "tier1"
        assert "tier1_findings" not in result
