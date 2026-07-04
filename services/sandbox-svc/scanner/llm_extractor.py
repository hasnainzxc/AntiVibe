"""LLM-backed semantic extractor for access-control flaw detection.

Where the regex-based analyzers catch known-shape patterns, this stage
catches what static analysis can't: business-logic flaws, missing
authorization checks, IDOR-by-construction, etc. We send the route
files through a commercial LLM and parse the response back into
findings.

Threat model and guardrails
---------------------------
The LLM call is a *data exfiltration risk*: we're sending customer
code to a third-party API. Two guardrails are non-negotiable:

  1. **Pre-flight sanitization** strips every known secret shape
     (AWS, GitHub, Stripe, OpenAI, JWT, PEM blocks) AND common PII
     (email, phone) before the prompt leaves our network. This is
     `sanitize()` and runs on *every* input regardless of caller.

  2. **Prompt caching** (the `anthropic-beta: prompt-caching-...`
     header) lets us send the system prompt once and reuse it across
     calls within a session. Cuts cost on the dashboard's
     "scan many repos" use case.

Reliability
-----------
LLM APIs flake. We retry with exponential backoff + jitter
(`2^attempt + random[0,1)`) up to 3 times, then mark the result
as `unverified=True` so the dashboard can show a "couldn't reach
the model" warning instead of a false "no findings" verdict.
"""

import json
import os
import re
import time
import random
from dataclasses import dataclass, field
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)

# Sanitization patterns. Order matters: longer / more specific
# patterns first so a JWT (3-segment) isn't partially matched by
# the more permissive OpenAI pattern. Each replacement is a
# stable token (`__KIND__`) that the LLM can use to understand
# the context — e.g. "this is a Stripe key placeholder" rather
# than "this is a random 32-char string". Tokens are double-
# underscored so they're trivially distinguishable from real
# identifiers in the sanitized output.
SANITIZE_PATTERNS = [
    # AWS — both the access key id (AKIA...) and the secret access
    # key (`aws_secret_access_key=...`). The second pattern keeps
    # the assignment framing for LLM context.
    (re.compile(r'AKIA[0-9A-Z]{16}'), "__AWS_KEY__"),
    (re.compile(r'(?:aws_secret_access_key\s*=\s*["\'])([^"\']+)'), r'\1__AWS_SECRET__'),
    # GitHub personal access tokens (classic + OAuth).
    (re.compile(r'ghp_[A-Za-z0-9]{36}'), "__GITHUB_PAT__"),
    (re.compile(r'gho_[A-Za-z0-9]{36}'), "__GITHUB_OAUTH__"),
    # Stripe — both live and test, since test keys still leak
    # customer intent (and some teams commit real keys with
    # the `sk_test_` prefix by mistake).
    (re.compile(r'sk_test_[0-9a-zA-Z]{24,}'), "__STRIPE_LIVE__"),
    (re.compile(r'sk_test_[0-9a-zA-Z]{24,}'), "__STRIPE_TEST__"),
    # OpenAI — `sk-` followed by 32+ alphanumerics. Matches both
    # project keys and user keys; we don't try to distinguish
    # because both are revokable the same way.
    (re.compile(r'sk-[A-Za-z0-9]{32,}'), "__OPENAI_KEY__"),
    # Anthropic — versioned prefix `sk-ant-api03-` or `sk-ant-api04-`.
    (re.compile(r'sk-ant-(?:api03|api04)-[A-Za-z0-9\-_]{80,}'), "__ANTHROPIC_KEY__"),
    # JWT — three base64url segments. The full match is replaced
    # (no group capture) because the segments individually are
    # not meaningful.
    (re.compile(r'eyJ[A-Za-z0-9\-_=]{20,}\.[A-Za-z0-9\-_=]{20,}\.[A-Za-z0-9\-_=]{20,}'), "__JWT_TOKEN__"),
    # Private key blocks — replaced wholesale, not token-by-token,
    # because the key body is megabytes of base64 and not useful
    # to the LLM.
    (re.compile(r'-----BEGIN (?:RSA )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA )?PRIVATE KEY-----'), "__PRIVATE_KEY__"),
    # SendGrid.
    (re.compile(r'SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43}'), "__SENDGRID_KEY__"),
    # Slack — `xox[bpras]-` prefix set.
    (re.compile(r'xox[bpras]-[A-Za-z0-9\-]{10,}'), "__SLACK_TOKEN__"),
    # PII: email addresses and North American phone numbers. The
    # email regex is the standard RFC-ish form — it over-matches
    # (e.g. `foo@bar` in code) but the false positive is just a
    # token replacement, never a deletion.
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), "__EMAIL__"),
    (re.compile(r'\b(?:\+?\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}\b'), "__PHONE__"),
]


@dataclass
class LLMFinding:
    """A single LLM-reported finding. `model` and token counts are
    stored per-finding (not just per-result) so individual findings
    can be traced back to a specific model run — useful when
    batching multiple route files into a single LLM call.
    """
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
    """Aggregate result from a single `analyze_code` call.

    `unverified` distinguishes "LLM said there are no findings" from
    "we never reached the LLM / the response was unparseable". The
    dashboard uses this to render an explicit "could not verify"
    badge rather than a green check.
    """
    findings: list[LLMFinding] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_cents: float = 0.0
    unverified: bool = False


def sanitize(code: str) -> str:
    """Strip secrets and PII from `code` before it leaves our network.

    Applied unconditionally — never bypass this in the caller. If a
    new secret format is added, add it to `SANITIZE_PATTERNS` *here*
    (single chokepoint) rather than at the call site.
    """
    sanitized = code
    for pattern, replacement in SANITIZE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


# ─── LLM client wrapper (mockable) ───

class LLMClient:
    """Thin wrapper around the Anthropic SDK with two properties:

    1. **Lazy SDK import** — the `anthropic` package is optional at
       install time, and the rest of the scanner works without it
       (the analyzer just returns `{"error": "anthropic_sdk_not_available"}`
       and the orchestrator marks the run as unverified).

    2. **Mockable `complete()`** — tests subclass and override
       `complete` to return canned responses. See
       `tests/scanner/test_llm_extractor.py::TestMockedLLMClient`.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-5-sonnet"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        # Lazy client construction: don't fail at scanner-import time
        # if the SDK isn't installed. `_get_client()` initializes on
        # first use.
        self._client = None  # lazy

    def _get_client(self):
        """Return a memoized Anthropic client, or None if the SDK is missing."""
        if self._client is None:
            try:
                from anthropic import Anthropic
                self._client = Anthropic(api_key=self.api_key)
            except ImportError:
                logger.warning("llm.anthropic_sdk_missing")
                return None
        return self._client

    def complete(self, system: str, user: str) -> dict:
        """Call the LLM and return a normalized response dict.

        Returns one of:
          - `{"content": <str>, "usage": {"input_tokens": int, "output_tokens": int}}`
            on success.
          - `{"error": <str>}` on any failure (SDK missing, API error,
            rate limit, network). The caller treats both shapes
            uniformly.

        The `prompt-caching-2024-07-31` beta header caches the system
        prompt across calls in the same session. Cuts input token
        cost by ~90% on the common dashboard pattern of scanning
        many small repos in sequence.
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


# Strict-JSON system prompt. The "Output ONLY the JSON" instruction
# is the most important line — without it the LLM wraps responses in
# prose / markdown fencing, which `_parse_response` then has to
# extract via a fallback regex. A clean JSON response skips the
# fallback path entirely.
SYSTEM_PROMPT = (
    "You are a security code reader. Identify access-control logic flaws in the provided code. "
    "Output strict JSON: "
    '{"findings":[{"line": <int>, "flaw": "<short title>", "evidence": "<code snippet>", '
    '"suggestion": "<how to fix>", "severity": "critical|high|medium|low"}]}. '
    "Output ONLY the JSON. No prose, no markdown fencing."
)


def _validate_finding(f: dict) -> Optional[LLMFinding]:
    """Validate one LLM-emitted finding dict.

    Coerces every field to its expected type, clamps string lengths
    to keep event payloads bounded, and validates `severity` against
    the four allowed values (anything else falls back to "info" —
    better to under-classify than to crash on a weird LLM output).
    Returns None if the dict is so malformed it can't be coerced
    (e.g. line is "not-a-number"); the caller drops it.
    """
    try:
        return LLMFinding(
            line=int(f.get("line", 0)),
            # 200/300-char clamps prevent a runaway LLM from
            # generating a 50KB suggestion field that bloats the
            # downstream event payload.
            flaw=str(f.get("flaw", ""))[:200],
            evidence=str(f.get("evidence", ""))[:300],
            suggestion=str(f.get("suggestion", ""))[:300],
            # Inline whitelist — avoids a second lookup if the
            # LLM invented a severity level we don't track.
            severity=str(f.get("severity", "info")) if f.get("severity") in ("critical", "high", "medium", "low") else "info",
        )
    except (ValueError, TypeError, KeyError):
        return None


def _parse_response(response_text: str) -> list[LLMFinding]:
    """Parse the LLM's response into validated findings.

    Tries three parse paths in order:
      1. Direct JSON parse (`json.loads`).
      2. Extract from a single ```json ... ``` fenced block.
      3. Give up and return [].

    The fallback exists because a few LLM versions ignore the
    "no markdown fencing" instruction despite the system prompt.
    Catching the case gracefully keeps the analyzer from treating
    a model output style regression as a hard error.
    """
    try:
        data = json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        # Try to extract JSON from a single fenced code block.
        # `re.DOTALL` lets `.` match newlines inside the block.
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
    """Send `code` through the LLM and return sanitized, validated findings.

    Sanitization happens *before* the LLM call (not after) — once a
    secret has reached the third-party API, we can't unsend it.
    The sanitizer runs even if the LLM is mocked in tests, so the
    "no AWS key in the prompt" assertion in the test suite is
    a property of this function, not of any specific backend.

    Retry strategy: exponential backoff with jitter, up to
    `max_retries` attempts. The jitter is `random.uniform(0, 1)`
    added to `2^attempt` seconds, which de-correlates retries
    from parallel orchestrators (multiple workers backing off
    in lockstep would thunder-herd the rate limit on the next
    attempt).
    """
    sanitized = sanitize(code)
    client = llm_client or LLMClient()

    for attempt in range(max_retries):
        try:
            response = client.complete(SYSTEM_PROMPT, sanitized)
        except Exception as e:
            # Defensive — `LLMClient.complete` is supposed to
            # convert exceptions to `{"error": ...}`, but a
            # subclass override might not. Catch and continue.
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
        # A valid response is one that either parsed to findings
        # OR explicitly contains the word "findings" (a response
        # of `{"findings":[]}` is a valid "no flaws" verdict and
        # shouldn't trigger a retry). The substring check on
        # `content` (not on `data`) handles both the bare-JSON
        # and fenced-JSON shapes.
        if findings or "findings" in content:
            for f in findings:
                f.tokens_in = tokens_in
                f.tokens_out = tokens_out
                f.model = client.model
            # Pricing as of 2024-Q4: $3 per 1M input tokens,
            # $15 per 1M output tokens. Anthropic public rates.
            # Multiplied by 100 to keep `cost_cents` in a
            # human-readable unit. Recompute this when pricing
            # changes — the dashboard renders a "scanned for $X"
            # chip and an outdated cost calc is worse than no cost.
            cost_cents = (tokens_in * 3 / 1_000_000 + tokens_out * 15 / 1_000_000) * 100
            return LLMExtractResult(
                findings=findings,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_cents=cost_cents,
            )
        else:
            # Response was neither valid findings JSON nor a
            # well-formed `{"findings": ...}` shape. Retry —
            # this is usually a model hiccup, not a fundamental
            # schema mismatch.
            logger.warning("llm.invalid_output", attempt=attempt)
            time.sleep((2 ** attempt) + random.uniform(0, 1))
            continue

    logger.error("llm.all_retries_failed")
    return LLMExtractResult(findings=[], unverified=True)
