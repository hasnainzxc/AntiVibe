"""Tests for Tier 1 orchestrator."""

import tempfile
import json
import pytest
from pathlib import Path
import asyncio
from scanner.tier1 import run_tier1, run_tier1_sync, _merge_findings
from scanner.config_flaws import ConfigFlawFinding, Severity


def _write_file(base: Path, relpath: str, content: str):
    filepath = base / relpath
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content)


class TestTier1Chain:
    def test_clone_error_returns_error_status(self):
        result = run_tier1_sync("https://nonexistent.example.com/repo")
        assert result["status"] == "error"
        assert result["error"] is not None

    def test_unsupported_stack_returns_error(self, tmp_path, monkeypatch):
        def mock_clone(url, **kwargs):
            return str(tmp_path)
        monkeypatch.setattr("scanner.tier1.clone_repo", mock_clone)

        result = run_tier1_sync("https://fake/repo")
        assert result["status"] == "error"


class TestMergeFindings:
    def test_deduplicate_findings(self):
        secret_findings = []
        config_findings = [
            ConfigFlawFinding(
                file="firestore.rules", line=5, rule_id="FIRESTORE_OPEN_RW",
                title="Open Firestore", description="x",
                severity=Severity.CRITICAL, patch_md="fix"
            ),
            ConfigFlawFinding(
                file="firestore.rules", line=5, rule_id="FIRESTORE_OPEN_RW",
                title="Open Firestore", description="duplicate",
                severity=Severity.CRITICAL, patch_md="fix"
            ),
        ]
        llm_findings = []

        from scanner.ast_parser import ParseResult
        merged = _merge_findings(secret_findings, config_findings, llm_findings, ParseResult())
        # Should deduplicate the two identical config findings
        assert len(merged) == 1
        assert merged[0]["title"] == "Open Firestore"

    def test_merge_from_multiple_sources(self):
        config_findings = [
            ConfigFlawFinding(
                file="rules.txt", line=1, rule_id="TEST",
                title="Config issue", description="",
                severity=Severity.HIGH, patch_md="fix"
            ),
        ]

        class MockSecretFinding:
            file = "config.ts"
            line = 42
            key_type = "aws-key"
            severity = "critical"
            evidence = "masked"

        secret_findings = [MockSecretFinding()]

        class MockLLMFinding:
            line = 5
            flaw = "No auth check"
            evidence = "..."
            suggestion = "Add auth"
            severity = "high"
            model = "test"

        llm_findings = [MockLLMFinding()]

        from scanner.ast_parser import ParseResult
        merged = _merge_findings(secret_findings, config_findings, llm_findings, ParseResult())
        assert len(merged) == 3


class TestFullChainWithFixtures:
    def test_fixture_with_secret_finds_secret(self, tmp_path, monkeypatch):
        _write_file(tmp_path, "package.json", '{"dependencies":{"next":"14.0.0"}}')
        _write_file(tmp_path, "next.config.js", "module.exports = {}")
        _write_file(tmp_path, "app/layout.tsx", "export default function(){}")
        _write_file(tmp_path, "config.ts", 'const AWS_KEY = "AKIAIOSFODNN7EXAMPLE";')

        def mock_clone(url, **kwargs):
            return str(tmp_path)
        monkeypatch.setattr("scanner.tier1.clone_repo", mock_clone)

        result = run_tier1_sync("https://fake/repo")
        assert result["status"] in ("complete", "partial")
        secret_findings = [f for f in result["findings"] if f["source"] == "secret_detector"]
        assert len(secret_findings) >= 1

    def test_fixture_with_open_firestore_rules_finds_flaw(self, tmp_path, monkeypatch):
        _write_file(tmp_path, "package.json", '{"dependencies":{"next":"14.0.0"}}')
        _write_file(tmp_path, "next.config.js", "module.exports = {}")
        _write_file(tmp_path, "firestore.rules", "allow read, write: if true;\n")

        def mock_clone(url, **kwargs):
            return str(tmp_path)
        monkeypatch.setattr("scanner.tier1.clone_repo", mock_clone)

        result = run_tier1_sync("https://fake/repo")
        config_findings = [f for f in result["findings"] if f["source"] == "config_flaws"]
        assert len(config_findings) >= 1
        assert any("firestore" in f["title"].lower() for f in config_findings)


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_timeout_produces_partial_status(self, monkeypatch):
        # Set timeout to 1ms — will trigger if any step takes longer
        monkeypatch.setattr("scanner.tier1.TIER1_TIMEOUT", 0.001)

        def mock_clone(url, **kwargs):
            return "/tmp/mock-repo-cb"

        def mock_detect(path):
            from scanner.detect_stack import Stack
            return Stack.NEXTJS

        def mock_parse(repo_path, stack):
            import time
            time.sleep(0.01)  # 10ms > 1ms timeout -> triggers circuit-breaker
            from scanner.ast_parser import ParseResult
            return ParseResult()

        monkeypatch.setattr("scanner.tier1.clone_repo", mock_clone)
        monkeypatch.setattr("scanner.tier1.detect_stack", mock_detect)
        monkeypatch.setattr("scanner.tier1.parse_repo", mock_parse)

        result = await run_tier1("https://fake/repo")
        # Should be partial (circuit-breaker triggered after ast parse)
        assert result["status"] == "partial"
