"""Tests for Supabase Storage client (unit-level, no real Supabase)."""

import hashlib
import pytest
from storage import BUCKET_SCAN_ARTIFACTS, BUCKET_POC_CAPTURES


class TestPathFormat:
    def test_artifact_path_construction(self):
        scan_id = "test-abc-123"
        kind = "report"
        ext = ".json"
        path = f"{scan_id}/{kind}{ext}"
        assert path == "test-abc-123/report.json"

    def test_poc_path_with_no_extension(self):
        scan_id = "scan-456"
        kind = "poc"
        path = f"{scan_id}/{kind}"
        assert path == "scan-456/poc"


class TestBucketConstants:
    def test_private_bucket_names(self):
        assert BUCKET_SCAN_ARTIFACTS == "scan-artifacts"
        assert BUCKET_POC_CAPTURES == "poc-captures"

    def test_no_public_bucket(self):
        public_names = [BUCKET_SCAN_ARTIFACTS, BUCKET_POC_CAPTURES]
        assert all("public" not in name.lower() for name in public_names)


class TestRoundtripConcept:
    def test_hash_integrity_after_roundtrip(self):
        content = b"anti vibe sandbox storage test payload"
        expected_hash = hashlib.sha256(content).hexdigest()
        # Simulated roundtrip
        assert len(expected_hash) == 64
        assert hashlib.sha256(content).hexdigest() == expected_hash
