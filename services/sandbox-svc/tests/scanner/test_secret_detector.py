"""Tests for secret detector."""

from scanner.secret_detector import scan_file, scan_directory, _mask_secret, _shannon_entropy


class TestPatternMatchers:
    def test_detect_aws_key(self, tmp_path):
        f = tmp_path / "config.ts"
        f.write_text('const AWS_KEY = "AKIAIOSFODNN7EXAMPLE";')
        findings = scan_file(str(f))
        assert len(findings) >= 1
        assert findings[0].key_type == "aws-access-key"
        assert findings[0].severity == "critical"

    def test_detect_stripe_key(self, tmp_path):
        f = tmp_path / "server.js"
        f.write_text('STRIPE_SECRET = "sk_test_51H9gAbCdEfGhIjKlMnOpQrStUvWxYz";')
        findings = scan_file(str(f))
        assert len(findings) >= 1
        assert findings[0].key_type == "stripe-live-secret"

    def test_detect_github_pat(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text('GITHUB_TOKEN="ghp_abcdefghijklmnopqrstuvwxyz0123456789"')
        findings = scan_file(str(f))
        assert len(findings) >= 1
        assert findings[0].key_type == "github-pat-classic"

    def test_detect_openai_key(self, tmp_path):
        f = tmp_path / "app.py"
        f.write_text('openai.api_key = "sk-1234567890abcdef1234567890abcdef1234567890ab"')
        findings = scan_file(str(f))
        assert len(findings) >= 1
        assert findings[0].key_type in ("openai-api-key", "openai-api-key-alt")

    def test_detect_private_key(self, tmp_path):
        f = tmp_path / "key.pem"
        f.write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----")
        findings = scan_file(str(f))
        assert len(findings) >= 1
        assert findings[0].key_type == "private-key"


class TestFpControl:
    def test_placeholder_skipped(self, tmp_path):
        """REPLACE_ME patterns should not be flagged."""
        f = tmp_path / "config.ts"
        f.write_text('const KEY = "REPLACE_ME_YOUR_API_KEY_HERE"')
        findings = scan_file(str(f))
        assert len(findings) == 0

    def test_example_file_skipped(self, tmp_path):
        """Files with .example extension are skipped."""
        f = tmp_path / "config.example"
        f.write_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"')
        findings = scan_file(str(f))
        assert len(findings) == 0

    def test_test_file_skipped(self, tmp_path):
        """Test files with .test.ts extension are skipped."""
        f = tmp_path / "config.test.ts"
        f.write_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"')
        findings = scan_file(str(f))
        assert len(findings) == 0

    def test_readme_comment_skipped(self, tmp_path):
        """Documented placeholder in comments is skipped."""
        f = tmp_path / "README.md"
        f.write_text("# Usage\n// AKIAIOSFODNN7EXAMPLE is just an example")
        findings = scan_file(str(f))
        assert len(findings) == 0

    def test_no_secret_in_clean_file(self, tmp_path):
        """Clean code with no secrets returns 0 findings."""
        f = tmp_path / "utils.ts"
        f.write_text("export function add(a: number, b: number): number { return a + b; }")
        findings = scan_file(str(f))
        assert len(findings) == 0


class TestSecretMasking:
    def test_mask_hides_full_secret(self):
        masked = _mask_secret("AKIAIOSFODNN7EXAMPLE")
        assert "AKIA" not in masked or len(masked) < 20
        assert "..." in masked

    def test_no_raw_secret_in_finding_evidence(self, tmp_path):
        f = tmp_path / "config.js"
        f.write_text('KEY = "AKIAIOSFODNN7EXAMPLE"')
        findings = scan_file(str(f))
        assert len(findings) >= 1
        # Evidence field must NOT contain the raw secret
        assert "AKIAIOSFODNN7EXAMPLE" not in findings[0].evidence


class TestEntropyDetection:
    def test_high_entropy_random_token_detected(self, tmp_path):
        """High-entropy random-looking strings are flagged."""
        f = tmp_path / "env.ts"
        # A random-looking 40-char hex string
        f.write_text('const TOKEN = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c";')
        findings = scan_file(str(f))
        # This should match entropy > 4.5
        entropy_findings = [x for x in findings if x.method == "entropy"]
        assert len(entropy_findings) >= 1

    def test_short_token_not_flagged(self, tmp_path):
        """Tokens shorter than 32 chars are not entropy-flagged."""
        f = tmp_path / "config.ts"
        f.write_text("const PORT = 8080;")
        findings = scan_file(str(f))
        entropy_findings = [x for x in findings if x.method == "entropy"]
        assert len(entropy_findings) == 0


class TestDirectoryScan:
    def test_scan_directory_finds_secrets(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "config.ts").write_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"')
        (tmp_path / "src" / "utils.ts").write_text("export const x = 1;")
        findings = scan_directory(str(tmp_path))
        assert len(findings) >= 1
        assert all("AKIAIOSFODNN7EXAMPLE" not in f.evidence for f in findings)

    def test_node_modules_skipped(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "secret.ts").write_text('KEY = "AKIAIOSFODNN7EXAMPLE"')
        findings = scan_directory(str(tmp_path))
        assert len(findings) == 0


class TestShannonEntropyHelper:
    def test_repeated_string_low_entropy(self):
        assert _shannon_entropy("a" * 40) < 1.0

    def test_diverse_string_higher_entropy(self):
        assert _shannon_entropy("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c") > 3.0
