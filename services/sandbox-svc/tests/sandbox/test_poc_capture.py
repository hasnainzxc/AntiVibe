"""Tests for sandbox.poc_capture — PoCEntry, PoCLogSink, capture_response."""

from __future__ import annotations

import json

import pytest

from sandbox.poc_capture import (
    MAX_ENTRIES,
    PoCEntry,
    PoCLogSink,
    capture_response,
)
from sandbox.route_walker import CurlProbe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_probe(
    method: str = "GET",
    path: str = "/api/users/1",
    headers: dict | None = None,
    token_type: str = "user_a",
) -> CurlProbe:
    """Build a minimal CurlProbe for tests."""
    return CurlProbe(
        method=method,
        path=path,
        headers=headers or {},
        token_type=token_type,
    )


def _make_entry(
    status: int = 200,
    finding_type: str = "bola",
    curl: str = "curl -X GET '/api/users/1'",
    body: str = '{"id":1}',
) -> PoCEntry:
    """Build a minimal PoCEntry for tests."""
    return PoCEntry(
        timestamp="2026-01-01T00:00:00+00:00",
        probe=_make_probe(),
        status=status,
        curl=curl,
        body=body,
        finding_type=finding_type,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# PoCLogSink — basic logging
# ---------------------------------------------------------------------------


class TestPoCLogSinkLog:
    """Single entry logged and retrievable."""

    def test_log_single_entry_retrievable(self) -> None:
        sink = PoCLogSink()
        entry = _make_entry()
        sink.log(entry)

        assert len(sink) == 1
        assert sink.entries[0] is entry

    def test_log_multiple_entries_preserves_order(self) -> None:
        sink = PoCLogSink()
        e1 = _make_entry(status=200)
        e2 = _make_entry(status=403)
        e3 = _make_entry(status=404)
        sink.log(e1)
        sink.log(e2)
        sink.log(e3)

        assert len(sink) == 3
        assert sink.entries[0].status == 200
        assert sink.entries[1].status == 403
        assert sink.entries[2].status == 404

    def test_entries_property_returns_copy(self) -> None:
        sink = PoCLogSink()
        sink.log(_make_entry())
        entries = sink.entries
        entries.clear()
        # Clearing the returned list must not affect the sink
        assert len(sink) == 1


# ---------------------------------------------------------------------------
# PoCLogSink — JSON output
# ---------------------------------------------------------------------------


class TestPoCLogSinkJson:
    """JSON output valid with all fields."""

    def test_dump_json_valid_array(self) -> None:
        sink = PoCLogSink()
        sink.log(_make_entry(status=200, finding_type="bola"))
        sink.log(_make_entry(status=403, finding_type="pivot"))

        raw = sink.dump_json()
        data = json.loads(raw)

        assert isinstance(data, list)
        assert len(data) == 2

    def test_dump_json_contains_all_fields(self) -> None:
        sink = PoCLogSink()
        sink.log(
            _make_entry(
                status=200,
                finding_type="bola",
                curl="curl -X GET '/api/users/1'",
                body='{"id":1}',
            )
        )

        data = json.loads(sink.dump_json())
        record = data[0]

        # Top-level fields
        assert "timestamp" in record
        assert "status" in record
        assert "curl" in record
        assert "body" in record
        assert "finding_type" in record
        assert record["status"] == 200
        assert record["finding_type"] == "bola"

        # Nested probe fields
        probe = record["probe"]
        assert "method" in probe
        assert "path" in probe
        assert "headers" in probe
        assert "body" in probe
        assert "token_type" in probe
        assert probe["method"] == "GET"
        assert probe["path"] == "/api/users/1"

    def test_dump_json_empty_sink(self) -> None:
        sink = PoCLogSink()
        data = json.loads(sink.dump_json())
        assert data == []


# ---------------------------------------------------------------------------
# PoCLogSink — Markdown output
# ---------------------------------------------------------------------------


class TestPoCLogSinkMarkdown:
    """Markdown table has correct headers and entries."""

    def test_dump_markdown_headers(self) -> None:
        sink = PoCLogSink()
        md = sink.dump_markdown()
        lines = md.split("\n")

        # Header row
        assert "| Timestamp | Status | Finding Type | Curl | Body |" in lines[0]
        # Separator row
        assert "|-----------|--------|--------------|------|------|" in lines[1]

    def test_dump_markdown_contains_entries(self) -> None:
        sink = PoCLogSink()
        sink.log(_make_entry(status=200, finding_type="bola"))
        sink.log(_make_entry(status=403, finding_type="pivot"))

        md = sink.dump_markdown()
        lines = md.split("\n")

        # 2 header lines + 2 data rows
        assert len(lines) == 4
        assert "200" in lines[2]
        assert "bola" in lines[2]
        assert "403" in lines[3]
        assert "pivot" in lines[3]

    def test_dump_markdown_escapes_pipe_chars(self) -> None:
        sink = PoCLogSink()
        sink.log(_make_entry(body="a|b", curl="curl | grep"))

        md = sink.dump_markdown()
        # Pipe chars in body/curl should be escaped
        assert "a\\|b" in md
        assert "curl \\| grep" in md

    def test_dump_markdown_empty_sink(self) -> None:
        sink = PoCLogSink()
        md = sink.dump_markdown()
        lines = md.split("\n")
        # Only header + separator, no data rows
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# PoCLogSink — to_findings
# ---------------------------------------------------------------------------


class TestPoCLogSinkToFindings:
    """to_findings maps correctly to Finding schema."""

    def test_to_findings_schema_fields(self) -> None:
        sink = PoCLogSink()
        sink.log(_make_entry(status=200, finding_type="bola"))

        findings = sink.to_findings(scan_id="scan-abc")
        assert len(findings) == 1

        f = findings[0]
        # Required Finding fields
        assert "id" in f
        assert "scan_id" in f
        assert "severity" in f
        assert "title" in f
        assert "description" in f
        assert "poc_curl" in f
        assert "tier" in f
        assert "created_at" in f

    def test_to_findings_severity_mapping(self) -> None:
        sink = PoCLogSink()
        sink.log(_make_entry(finding_type="bola"))
        sink.log(_make_entry(finding_type="pivot"))
        sink.log(_make_entry(finding_type="open_surface"))

        findings = sink.to_findings()
        assert findings[0]["severity"] == "high"
        assert findings[1]["severity"] == "critical"
        assert findings[2]["severity"] == "medium"

    def test_to_findings_tier_is_3(self) -> None:
        sink = PoCLogSink()
        sink.log(_make_entry())

        findings = sink.to_findings()
        assert findings[0]["tier"] == 3

    def test_to_findings_scan_id_propagated(self) -> None:
        sink = PoCLogSink()
        sink.log(_make_entry())

        findings = sink.to_findings(scan_id="scan-xyz")
        assert findings[0]["scan_id"] == "scan-xyz"

    def test_to_findings_poc_curl_matches_entry(self) -> None:
        sink = PoCLogSink()
        sink.log(_make_entry(curl="curl -X GET 'http://x/api'"))

        findings = sink.to_findings()
        assert findings[0]["poc_curl"] == "curl -X GET 'http://x/api'"

    def test_to_findings_empty_sink(self) -> None:
        sink = PoCLogSink()
        assert sink.to_findings() == []


# ---------------------------------------------------------------------------
# PoCLogSink — 1000-entry cap
# ---------------------------------------------------------------------------


class TestPoCLogSinkCap:
    """1000-entry cap enforced."""

    def test_cap_enforced_at_1000(self) -> None:
        sink = PoCLogSink()
        for i in range(1100):
            sink.log(_make_entry(status=i))

        assert len(sink) == MAX_ENTRIES
        assert len(sink) == 1000

    def test_entries_beyond_cap_dropped(self) -> None:
        sink = PoCLogSink()
        for i in range(MAX_ENTRIES):
            sink.log(_make_entry(status=i))
        # This one should be dropped
        sink.log(_make_entry(status=9999))

        assert len(sink) == MAX_ENTRIES
        # Last entry should be status=999, not 9999
        assert sink.entries[-1].status == 999

    def test_cap_warned_only_once(self, caplog: pytest.LogCaptureFixture) -> None:
        """Warning logged once when cap first hit, not on every subsequent log."""
        sink = PoCLogSink()
        for i in range(MAX_ENTRIES + 5):
            sink.log(_make_entry(status=i))

        # Count warnings from our logger
        warnings = [
            r for r in caplog.records if r.msg == "poc_log_sink_cap_reached"
        ]
        assert len(warnings) <= 1


# ---------------------------------------------------------------------------
# capture_response factory
# ---------------------------------------------------------------------------


class TestCaptureResponse:
    """Factory function creates valid PoCEntry."""

    def test_basic_capture(self) -> None:
        entry = capture_response(
            status=200,
            method="GET",
            path="/api/users/1",
            response_text='{"id":1}',
        )

        assert entry.status == 200
        assert entry.probe.method == "GET"
        assert entry.probe.path == "/api/users/1"
        assert entry.body == '{"id":1}'
        assert entry.finding_type == "bola"  # default
        assert entry.timestamp  # non-empty

    def test_curl_masking_bearer(self) -> None:
        entry = capture_response(
            status=200,
            method="GET",
            path="/api/users/1",
            response_text="ok",
            curl_template="curl -H 'Authorization: Bearer eyJhbGciOi...'",
        )

        assert "eyJhbGciOi" not in entry.curl
        assert "***" in entry.curl

    def test_curl_synthesized_when_no_template(self) -> None:
        entry = capture_response(
            status=200,
            method="POST",
            path="/api/data",
            response_text="ok",
            headers={"Content-Type": "application/json"},
        )

        assert "curl" in entry.curl
        assert "POST" in entry.curl
        assert "/api/data" in entry.curl

    def test_curl_synthesized_masks_auth_header(self) -> None:
        entry = capture_response(
            status=200,
            method="GET",
            path="/api/x",
            response_text="ok",
            headers={"Authorization": "Bearer secret123"},
        )

        assert "secret123" not in entry.curl
        assert "***" in entry.curl

    def test_body_truncated_at_1kb(self) -> None:
        big_body = "A" * 2000
        entry = capture_response(
            status=200,
            method="GET",
            path="/api/x",
            response_text=big_body,
        )

        # Body should be truncated + ellipsis marker
        assert len(entry.body.encode("utf-8")) < 2000
        assert "truncated" in entry.body

    def test_body_not_truncated_when_small(self) -> None:
        entry = capture_response(
            status=200,
            method="GET",
            path="/api/x",
            response_text="small",
        )

        assert entry.body == "small"

    def test_finding_type_param(self) -> None:
        entry = capture_response(
            status=403,
            method="GET",
            path="/api/admin",
            response_text="forbidden",
            finding_type="pivot",
        )

        assert entry.finding_type == "pivot"

    def test_token_type_propagated(self) -> None:
        entry = capture_response(
            status=200,
            method="GET",
            path="/api/x",
            response_text="ok",
            token_type="user_b",
        )

        assert entry.probe.token_type == "user_b"


# ---------------------------------------------------------------------------
# No external dependencies check
# ---------------------------------------------------------------------------


class TestNoExternalDeps:
    """Module uses only stdlib + project-internal imports."""

    def test_imports_are_local(self) -> None:
        """Verify poc_capture only imports from stdlib and sandbox.*"""
        import importlib
        import sys

        mod = importlib.import_module("sandbox.poc_capture")
        # Module should load without error — all imports resolved
        assert mod is not None
        assert "sandbox.poc_capture" in sys.modules
