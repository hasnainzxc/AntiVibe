"""PoC capture and log sink for sandbox scan results.

Captures HTTP probe responses as structured PoC entries, stores them in-memory
with a 1000-entry cap to prevent OOM on runaway fuzz loops, and exports to
JSON, Markdown, or Finding-compatible dicts for Tier 3 output.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

import structlog

from sandbox.route_walker import CurlProbe

logger = structlog.get_logger(__name__)

# Max entries per scan to prevent OOM on runaway fuzz loops
MAX_ENTRIES = 1000

# Body truncation limit (first 1KB)
MAX_BODY_BYTES = 1024

FindingType = Literal["bola", "pivot", "open_surface"]


@dataclass
class PoCEntry:
    """Single captured PoC from an HTTP probe response.

    Fields:
        timestamp:     ISO 8601 UTC timestamp when entry was captured.
        probe:         The CurlProbe that generated this response.
        status:        HTTP status code from the response.
        curl:          Masked curl command (auth tokens redacted).
        body:          Response body truncated to first 1KB.
        finding_type:  Category of finding: "bola", "pivot", or "open_surface".
    """

    timestamp: str
    probe: CurlProbe
    status: int
    curl: str
    body: str
    finding_type: FindingType


class PoCLogSink:
    """In-memory log sink for PoC entries with 1000-entry cap.

    Appends entries to an internal list. When the cap is reached, further
    log() calls are silently dropped and a warning is logged once.
    """

    def __init__(self) -> None:
        self._entries: list[PoCEntry] = []
        self._cap_warned: bool = False

    def log(self, entry: PoCEntry) -> None:
        """Append entry to in-memory list. Drops if cap reached."""
        if len(self._entries) >= MAX_ENTRIES:
            if not self._cap_warned:
                logger.warning(
                    "poc_log_sink_cap_reached",
                    max_entries=MAX_ENTRIES,
                )
                self._cap_warned = True
            return
        self._entries.append(entry)

    def dump_json(self) -> str:
        """Serialize all entries as JSON array.

        Each entry becomes a dict with all fields. CurlProbe is serialized
        as a nested dict with method, path, headers, body, token_type.
        """
        records = []
        for entry in self._entries:
            records.append(
                {
                    "timestamp": entry.timestamp,
                    "probe": {
                        "method": entry.probe.method,
                        "path": entry.probe.path,
                        "headers": entry.probe.headers,
                        "body": entry.probe.body,
                        "token_type": entry.probe.token_type,
                    },
                    "status": entry.status,
                    "curl": entry.curl,
                    "body": entry.body,
                    "finding_type": entry.finding_type,
                }
            )
        return json.dumps(records, indent=2)

    def dump_markdown(self) -> str:
        """Render entries as markdown table with masked curl blocks.

        Columns: Timestamp | Status | Finding Type | Curl | Body
        """
        lines = [
            "| Timestamp | Status | Finding Type | Curl | Body |",
            "|-----------|--------|--------------|------|------|",
        ]
        for entry in self._entries:
            # Escape pipe chars in body/curl for markdown table safety
            safe_curl = entry.curl.replace("|", "\\|")
            safe_body = entry.body.replace("|", "\\|")
            lines.append(
                f"| {entry.timestamp} "
                f"| {entry.status} "
                f"| {entry.finding_type} "
                f"| `{safe_curl}` "
                f"| `{safe_body}` |"
            )
        return "\n".join(lines)

    def to_findings(self, scan_id: str = "") -> list[dict]:
        """Convert entries to Finding-compatible dicts for Tier 3 output.

        Maps to the canonical Finding schema from shared-types:
        id, scan_id, severity, title, description, poc_curl, tier, created_at.

        Severity mapping:
          - bola -> high
          - pivot -> critical
          - open_surface -> medium
        """
        severity_map: dict[FindingType, str] = {
            "bola": "high",
            "pivot": "critical",
            "open_surface": "medium",
        }
        title_map: dict[FindingType, str] = {
            "bola": "BOLA: Broken Object Level Authorization",
            "pivot": "Pivot: Horizontal privilege escalation via token swap",
            "open_surface": "Open Surface: Unauthenticated endpoint exposed",
        }

        findings = []
        for entry in self._entries:
            findings.append(
                {
                    "id": f"poc-{uuid.uuid4().hex[:12]}",
                    "scan_id": scan_id,
                    "severity": severity_map.get(entry.finding_type, "medium"),
                    "title": title_map.get(
                        entry.finding_type,
                        f"PoC: {entry.finding_type}",
                    ),
                    "description": (
                        f"HTTP {entry.status} on {entry.probe.method} "
                        f"{entry.probe.path} — {entry.finding_type}"
                    ),
                    "poc_curl": entry.curl,
                    "tier": 3,
                    "created_at": entry.timestamp,
                }
            )
        return findings

    @property
    def entries(self) -> list[PoCEntry]:
        """Read-only access to logged entries."""
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


def _mask_curl(curl_cmd: str) -> str:
    """Mask Authorization header values in a curl command string.

    Replaces Bearer tokens and other auth header values with '***'.
    """
    import re

    # Mask "Authorization: Bearer <token>" patterns
    masked = re.sub(
        r"(-H\s+['\"]Authorization:\s*Bearer\s+)[^'\"]*(['\"])",
        r"\1***\2",
        curl_cmd,
        flags=re.IGNORECASE,
    )
    # Mask generic "Authorization: <value>" patterns
    masked = re.sub(
        r"(-H\s+['\"]Authorization:\s*)(?!Bearer\s)[^'\"]*(['\"])",
        r"\1***\2",
        masked,
        flags=re.IGNORECASE,
    )
    return masked


def _truncate_body(text: str, max_bytes: int = MAX_BODY_BYTES) -> str:
    """Truncate response body to first max_bytes."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="replace") + "…[truncated]"


def capture_response(
    status: int,
    method: str,
    path: str,
    response_text: str,
    *,
    finding_type: FindingType = "bola",
    curl_template: Optional[str] = None,
    headers: Optional[dict] = None,
    token_type: str = "none",
) -> PoCEntry:
    """Factory: create a PoCEntry from an HTTP response.

    Args:
        status:          HTTP status code.
        method:          HTTP method (GET, POST, etc.).
        path:            Request path.
        response_text:   Response body text.
        finding_type:    Category of finding (default "bola").
        curl_template:   Optional curl command string. If provided, auth
                         headers are masked. If None, a basic curl is
                         synthesized from method/path/headers.
        headers:         Optional request headers dict.
        token_type:      Token type used ("none", "user_a", "user_b").

    Returns:
        PoCEntry with timestamp, masked curl, truncated body.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Build or mask curl command
    if curl_template:
        masked_curl = _mask_curl(curl_template)
    else:
        # Synthesize a basic curl command
        parts = [f"curl -X {method}"]
        if headers:
            for k, v in headers.items():
                if k.lower() == "authorization":
                    parts.append(f"-H '{k}: ***'")
                else:
                    parts.append(f"-H '{k}: {v}'")
        parts.append(f"'{path}'")
        masked_curl = " ".join(parts)

    # Build a minimal CurlProbe for the entry
    probe = CurlProbe(
        method=method,
        path=path,
        headers=headers or {},
        token_type=token_type,
    )

    truncated_body = _truncate_body(response_text)

    return PoCEntry(
        timestamp=now,
        probe=probe,
        status=status,
        curl=masked_curl,
        body=truncated_body,
        finding_type=finding_type,
    )
