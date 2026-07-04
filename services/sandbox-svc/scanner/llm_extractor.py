"""LLM semantic extractor: wraps commercial LLM (Anthropic default) with secret sanitization."""

import json
import os
import re
import time
import random
from dataclasses import dataclass, field
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)

# Sanitization patterns - replace secret-looking content with placeholders
SANITIZE_PATTERNS = [
    # AWS
    (re.compile(r'AKIA[0-9A-Z]{16}'), "__AWS_KEY__"),
    (re.compile(r'(?:aws_secret_access_key\s*=\s*["\'])([^"\']+)'), r'\1__AWS_SECRET__'),
    # GitHub
    (re.compile(r'ghp_[A-Za-z0-9]{36}'), "__GITHUB_PAT__"),
    (re.compile(r'gho_[A-Za-z0-9]{36}'), "__GITHUB_OAUTH__"),
    # Stripe
    (re.compile(r'sk_test_[0-9a-zA-Z]{24,}'), "__STRIPE_LIVE__"),
    (re.compile(r'sk_test_[0-9a-zA-Z]{24,}'), "__STRIPE_TEST__"),
    # OpenAI
    (re.compile(r'sk-[A-Za-z0-9]{32,}'), "__OPENAI_KEY__"),
    # Anthropic
    (re.compile(r'sk-ant-(?:api03|api04)-[A-Za-z0-9\-_]{80,}'), "__ANTHROPIC_KEY__"),
    # JWT
    (re.compile(r'eyJ[A-Za-z0-9\-_=]{20,}\.[A-Za-z0-9\-_=]{20,}\.[A-Za-z0-9\-_=]{20,}'), "__JWT_TOKEN__"),
    # Private keys
    (re.compile(r'-----BEGIN (?:RSA )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA )?PRIVATE KEY-----'), "__PRIVATE_KEY__"),
    # SendGrid
    (re.compile(r'SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43}'), "__SENDGRID_KEY__"),
    # Slack
    (re.compile(r'xox[bpras]-[A-Za-z0-9\-]{10,}'), "__SLACK_TOKEN__"),
    # PII patterns
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), "__EMAIL__"),
    (re.compile(r'\b(?:\+?\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}\b'), "__PHONE__"),
]


@dataclass
class LLMFinding:
    line: int = 0
    flaw: str = ""
    evidence: str = ""
    suggestion: str = ""
    severity: str = "info"
    model: str = "claude-3-5-sonnet"
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class LLMExtractResult:
    findings: list[LLMFinding] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_cents: float = 0.0
    unverified: bool = False


def sanitize(code: str) -> str:
    """Strip secrets and PII from code before sending to LLM."""
    sanitized = code
    for pattern, replacement in SANITIZE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


# ─── LLM client wrapper (mockable) ───

class LLMClient:
    """Anthropic API client wrapper. Replaceable for testing."""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-5-sonnet"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self._client = None  # lazy

    def _get_client(self):
        if self._client is None:
            try:
                from anthropic import Anthropic
                self._client = Anthropic(api_key=self.api_key)
            except ImportError:
                logger.warning("llm.anthropic_sdk_missing")
                return None
        return self._client

    def complete(self, system: str, user: str) -> dict:
        """Call LLM with system + user message. Returns response dict.

        Real call uses Anthropic SDK. For tests, override this method via mocking.
        """
        client = self._get_client()
        if client is None:
            return {"error": "anthropic_sdk_not_available"}

        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user}],
                extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
            )
            return {
                "content": response.content[0].text,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            }
        except Exception as e:
            logger.error("llm.api_error", error=str(e))
            return {"error": str(e)}


SYSTEM_PROMPT = (
    "You are a security code reader. Identify access-control logic flaws in the provided code. "
    "Output strict JSON: "
    '{"findings":[{"line": <int>, "flaw": "<short title>", "evidence": "<code snippet>", '
    '"suggestion": "<how to fix>", "severity": "critical|high|medium|low"}]}. '
    "Output ONLY the JSON. No prose, no markdown fencing."
)


def _validate_finding(f: dict) -> Optional[LLMFinding]:
    """Validate a single finding dict. Returns LLMFinding or None if invalid."""
    try:
        return LLMFinding(
            line=int(f.get("line", 0)),
            flaw=str(f.get("flaw", ""))[:200],
            evidence=str(f.get("evidence", ""))[:300],
            suggestion=str(f.get("suggestion", ""))[:300],
            severity=str(f.get("severity", "info")) if f.get("severity") in ("critical", "high", "medium", "low") else "info",
        )
    except (ValueError, TypeError, KeyError):
        return None


def _parse_response(response_text: str) -> list[LLMFinding]:
    """Parse LLM JSON response. Returns validated findings."""
    try:
        data = json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        # Try to extract JSON from markdown fencing
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

    if not isinstance(data, dict):
        return []
    raw_findings = data.get("findings", [])
    if not isinstance(raw_findings, list):
        return []

    findings = []
    for rf in raw_findings:
        validated = _validate_finding(rf)
        if validated is not None:
            findings.append(validated)
    return findings


def analyze_code(code: str, llm_client: Optional[LLMClient] = None, max_retries: int = 3) -> LLMExtractResult:
    """Analyze code for security flaws via LLM. Returns LLMExtractResult.

    Sanitizes input first, retries with jitter on failure, gracefully handles
    schema-invalid responses.
    """
    sanitized = sanitize(code)
    client = llm_client or LLMClient()

    for attempt in range(max_retries):
        try:
            response = client.complete(SYSTEM_PROMPT, sanitized)
        except Exception as e:
            logger.warning("llm.call_failed", attempt=attempt, error=str(e))
            time.sleep((2 ** attempt) + random.uniform(0, 1))
            continue

        if "error" in response:
            logger.warning("llm.response_error", attempt=attempt, error=response["error"])
            time.sleep((2 ** attempt) + random.uniform(0, 1))
            continue

        content = response.get("content", "")
        usage = response.get("usage", {})
        tokens_in = usage.get("input_tokens", 0)
        tokens_out = usage.get("output_tokens", 0)

        findings = _parse_response(content)
        if findings or "findings" in content:  # valid response (even if empty list)
            for f in findings:
                f.tokens_in = tokens_in
                f.tokens_out = tokens_out
                f.model = client.model
            # Cost calculation (rough): $3/1M input, $15/1M output
            cost_cents = (tokens_in * 3 / 1_000_000 + tokens_out * 15 / 1_000_000) * 100
            return LLMExtractResult(
                findings=findings,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_cents=cost_cents,
            )
        else:
            logger.warning("llm.invalid_output", attempt=attempt)
            time.sleep((2 ** attempt) + random.uniform(0, 1))
            continue

    logger.error("llm.all_retries_failed")
    return LLMExtractResult(findings=[], unverified=True)
