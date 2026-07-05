"""Tests for LLM prompt sanitization — secrets stripped before API call."""

import pytest
from scanner.llm_extractor import (
    sanitize,
    analyze_code,
    LLMClient,
    LLMExtractResult,
)


class TestSanitizationPatterns:
    """Verify specific secret patterns are replaced by sanitize()."""

    def test_aws_key_sanitized(self):
        code = 'aws_key = "AKIAIOSFODNN7EXAMPLE"'
        result = sanitize(code)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "__AWS_KEY__" in result

    def test_stripe_live_key_sanitized(self):
        code = 'stripe = "sk_test_51H9gAbCdEfGhIjKlMnOpQrStUvWxYz"'
        result = sanitize(code)
        assert "sk_test_" not in result
        assert "__STRIPE_LIVE__" in result

    def test_github_pat_sanitized(self):
        code = 'token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"'
        result = sanitize(code)
        assert "ghp_" not in result
        assert "__GITHUB_PAT__" in result

    def test_non_secret_preserved(self):
        code = "const x = 1;"
        result = sanitize(code)
        assert result == code

    def test_multiple_secrets_all_sanitized(self):
        code = (
            'aws = "AKIAIOSFODNN7EXAMPLE"\n'
            'stripe = "sk_test_51H9gAbCdEfGhIjKlMnOpQrStUvWxYz"\n'
            'github = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"\n'
            "const x = 1;\n"
        )
        result = sanitize(code)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "sk_test_" not in result
        assert "ghp_" not in result
        assert "__AWS_KEY__" in result
        assert "__STRIPE_LIVE__" in result
        assert "__GITHUB_PAT__" in result
        assert "const x = 1;" in result


class TestSanitizationBeforeApi:
    """Sanitization happens BEFORE the LLM call (mock API)."""

    def test_sanitization_before_mocked_api_call(self):
        code = 'aws_key = "AKIAIOSFODNN7EXAMPLE"\nconst x = 1;'

        class CaptureClient(LLMClient):
            def __init__(self):
                super().__init__(api_key="sk-ant-test123")
                self.sent = None

            def complete(self, system, user):
                self.sent = user
                return {
                    "content": '{"findings":[]}',
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                }

        client = CaptureClient()
        result = analyze_code(code, llm_client=client)
        assert client.sent is not None
        assert "AKIAIOSFODNN7EXAMPLE" not in client.sent
        assert "__AWS_KEY__" in client.sent
        assert "const x = 1;" in client.sent
        assert isinstance(result, LLMExtractResult)
