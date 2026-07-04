"""Tests for config-flaw analyzer."""

import tempfile
from pathlib import Path
from scanner.config_flaws import (
    analyze_config_flaws,
    ConfigFlawFinding,
    Severity,
)


def _write_file(base: Path, relpath: str, content: str):
    filepath = base / relpath
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content)


class TestFirestoreRules:
    def test_open_rw_detected(self, tmp_path):
        _write_file(tmp_path, "firestore.rules", "rules_version = '2';\nservice cloud.firestore {\n  match /databases/{database}/documents {\n    match /users/{userId} {\n      allow read, write: if true;\n    }\n  }\n}\n")
        findings = analyze_config_flaws(str(tmp_path), "firebase")
        rule_ids = {f.rule_id for f in findings}
        assert "FIRESTORE_OPEN_RW" in rule_ids

    def test_open_rw_has_patch_md(self, tmp_path):
        _write_file(tmp_path, "firestore.rules", "allow read, write: if true;\n")
        findings = analyze_config_flaws(str(tmp_path), "firebase")
        assert len(findings) >= 1
        assert findings[0].patch_md
        assert "request.auth" in findings[0].patch_md

    def test_no_firestore_rules_returns_empty(self, tmp_path):
        findings = analyze_config_flaws(str(tmp_path), "nextjs")
        assert all(f.rule_id != "FIRESTORE_OPEN_RW" for f in findings)

    def test_safe_rules_no_findings(self, tmp_path):
        _write_file(tmp_path, "firestore.rules", "allow read, write: if request.auth != null;\n")
        findings = analyze_config_flaws(str(tmp_path), "firebase")
        assert all(f.rule_id != "FIRESTORE_OPEN_RW" for f in findings)


class TestCORS:
    def test_cors_wildcard_with_auth_flagged(self, tmp_path):
        _write_file(tmp_path, "next.config.js", "module.exports = { headers: [{ 'Access-Control-Allow-Origin': '*' }] };")
        _write_file(tmp_path, "app/api/users/route.ts", "export async function GET(req: Request) { const auth = req.headers.get('Authorization'); return Response.json({}); }")
        findings = analyze_config_flaws(str(tmp_path), "nextjs")
        cors_findings = [f for f in findings if f.rule_id == "CORS_WILDCARD_AUTH"]
        assert len(cors_findings) >= 1


class TestIAM:
    def test_broad_s3_policy_flagged(self, tmp_path):
        _write_file(tmp_path, "aws/iam.policies", json_string := '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:*","Resource":"*"}]}')
        findings = analyze_config_flaws(str(tmp_path), "express")
        iam_findings = [f for f in findings if f.rule_id == "IAM_BROAD_S3"]
        assert len(iam_findings) >= 1


class TestPermissiveAuth:
    def test_no_op_express_middleware_flagged(self, tmp_path):
        _write_file(tmp_path, "app.js", "const express = require('express');\nconst app = express();\napp.use((req, res, next) => next());\n")
        findings = analyze_config_flaws(str(tmp_path), "express")
        auth_findings = [f for f in findings if f.rule_id == "EXPRESS_NOOP_AUTH"]
        assert len(auth_findings) >= 1


class TestMissingHelmet:
    def test_express_without_helmet(self, tmp_path):
        _write_file(tmp_path, "package.json", '{"dependencies":{"express":"4.18.0"}}')
        findings = analyze_config_flaws(str(tmp_path), "express")
        helmet_findings = [f for f in findings if f.rule_id == "NO_HELMET"]
        assert len(helmet_findings) >= 1
        assert helmet_findings[0].severity == Severity.MEDIUM

    def test_express_with_helmet_no_finding(self, tmp_path):
        _write_file(tmp_path, "package.json", '{"dependencies":{"express":"4.18.0","helmet":"7.0.0"}}')
        findings = analyze_config_flaws(str(tmp_path), "express")
        assert all(f.rule_id != "NO_HELMET" for f in findings)


class TestGeneral:
    def test_not_a_directory_returns_empty(self):
        findings = analyze_config_flaws("/nonexistent/path/xyz", "nextjs")
        assert findings == []

    def test_clean_repo_no_findings(self, tmp_path):
        _write_file(tmp_path, "package.json", '{"dependencies":{"next":"14.0.0"}}')
        findings = analyze_config_flaws(str(tmp_path), "nextjs")
        assert all(f.severity != Severity.CRITICAL for f in findings)
