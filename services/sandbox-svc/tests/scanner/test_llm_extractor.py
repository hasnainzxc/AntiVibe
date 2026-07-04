"""Tests for LLM semantic extractor with sanitization."""

import json
import pytest
from scanner.llm_extractor import (
    sanitize,
    analyze_code,
    LLMClient,
    LLMFinding,
    LLMExtractResult,
    _parse_response,
)


class TestSanitize:
    def test_strips_aws_key(self):
        code = 'const key = "AKIAIOSFODNN7EXAMPLE";'
        result = sanitize(code)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "__AWS_KEY__" in result

    def test_strips_github_pat(self):
        code = 'GITHUB_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"'
        result = sanitize(code)
        assert "ghp_abcdef" not in result
        assert "__GITHUB_PAT__" in result

    def test_strips_stripe_live(self):
        code = 'STRIPE = "sk_test_51H9gAbCdEfGhIjKlMnOpQrStUvWxYz"'
        result = sanitize(code)
        assert "sk_test_" not in result
        assert "__STRIPE_LIVE__" in result

    def test_strips_openai_key(self):
        code = 'OPENAI_KEY = "sk-1234567890abcdef1234567890abcdef1234567890ab"'
        result = sanitize(code)
        assert "sk-1234" not in result
        assert "__OPENAI_KEY__" in result

    def test_strips_jwt(self):
        code = 'token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"'
        result = sanitize(code)
        assert "eyJ" not in result
        assert "__JWT_TOKEN__" in result

    def test_strips_email_pii(self):
        code = 'user_email = "user@example.com"'
        result = sanitize(code)
        assert "user@example.com" not in result
        assert "__EMAIL__" in result

    def test_strips_private_key_block(self):
        code = '''-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA...
-----END RSA PRIVATE KEY-----'''
        result = sanitize(code)
        assert "BEGIN RSA PRIVATE KEY" not in result
        assert "__PRIVATE_KEY__" in result

    def test_preserves_normal_code(self):
        code = "function add(a, b) { return a + b; }"
        result = sanitize(code)
        assert result == code


class TestMockedLLMClient:
    """Mock LLM client to test analyze_code without real API."""

    def _make_client(self, response_text: str, tokens_in=100, tokens_out=50):
        class MockClient(LLMClient):
            def complete(self, system, user):
                return {
                    "content": response_text,
                    "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out},
                }
        return MockClient(api_key="mock", model="mock-model")

    def test_analyze_code_with_sanitization(self):
        """Sanitization happens BEFORE LLM call."""
        code = 'const AWS_KEY = "AKIAIOSFODNN7EXAMPLE";\nfunction getUser(req) { return db.find(req.params.id); }'
        client = self._make_client('{"findings":[{"line":2,"flaw":"No auth check","severity":"high"}]}')
        # Patch the client to capture what was sent
        sent_payload = []
        original_complete = client.complete
        def capture(system, user):
            sent_payload.append(user)
            return original_complete(system, user)
        client.complete = capture

        result = analyze_code(code, llm_client=client)
        assert len(sent_payload) == 1
        assert "AKIAIOSFODNN7EXAMPLE" not in sent_payload[0]
        assert "__AWS_KEY__" in sent_payload[0]

    def test_analyze_code_parses_valid_response(self):
        client = self._make_client(
            '{"findings":[{"line":5,"flaw":"SQL injection","evidence":"raw query","suggestion":"parameterize","severity":"critical"}]}'
        )
        result = analyze_code("const x = 1;", llm_client=client)
        assert len(result.findings) == 1
        assert result.findings[0].flaw == "SQL injection"
        assert result.findings[0].severity == "critical"
        assert result.tokens_in == 100
        assert result.tokens_out == 50

    def test_analyze_code_handles_schema_violation_gracefully(self):
        """Invalid JSON / schema doesn't crash; just returns empty."""
        client = self._make_client('{"unknown_field": "x"}')
        result = analyze_code("const x = 1;", llm_client=client)
        # Either empty findings OR unverified is acceptable graceful behavior
        assert isinstance(result, LLMExtractResult)
        assert result.findings == [] or result.unverified is True

    def test_analyze_code_retries_on_error(self):
        """Failures retry with jitter; final failure marks unverified."""
        class FlakyClient(LLMClient):
            def __init__(self):
                self.attempts = 0
            def complete(self, system, user):
                self.attempts += 1
                if self.attempts < 3:
                    return {"error": "rate_limited"}
                return {"content": '{"findings":[]}', "usage": {"input_tokens": 50, "output_tokens": 10}}

        client = FlakyClient()
        result = analyze_code("test", llm_client=client, max_retries=3)
        assert client.attempts == 3
        assert not result.unverified
        assert result.tokens_in == 50


class TestParseResponse:
    def test_valid_json(self):
        text = '{"findings":[{"line":1,"flaw":"x","severity":"high"}]}'
        result = _parse_response(text)
        assert len(result) == 1
        assert result[0].line == 1

    def test_invalid_json_returns_empty(self):
        result = _parse_response("not json at all")
        assert result == []

    def test_markdown_fenced_json(self):
        text = '```json\n{"findings":[{"line":1,"flaw":"x","severity":"high"}]}\n```'
        result = _parse_response(text)
        assert len(result) == 1

    def test_invalid_finding_skipped(self):
        text = '{"findings":[{"line":"not-a-number"},{"line":1,"flaw":"x","severity":"high"}]}'
        result = _parse_response(text)
        # First one fails (line must be int), second succeeds
        assert len(result) == 1
        assert result[0].line == 1

    def test_severity_validation(self):
        text = '{"findings":[{"line":1,"flaw":"x","severity":"super-critical"}]}'
        result = _parse_response(text)
        assert result[0].severity == "info"
