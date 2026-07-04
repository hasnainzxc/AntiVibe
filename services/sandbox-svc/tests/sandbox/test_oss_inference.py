"""Tests for OSS inference client — Tier 3 fuzz-pattern generator.

All httpx calls are mocked via `respx` (same pattern as
`tests/fly/test_client.py`). The `_post_chat_completion` method
is also reachable directly for tests that want to bypass
httpx entirely. Zero real network egress; the test file
explicitly asserts no real LLM API call is made.
"""

import json

import httpx
import pytest
import respx

from sandbox.oss_inference import (
    FuzzPattern,
    OSSInferenceClient,
    Response,
    SYSTEM_PROMPT,
    TokenUsage,
    _build_curl,
    _parse_response,
    _validate_pattern,
)
from sandbox.route_mapper import RouteIndexEntry


# ─── Helpers ─────────────────────────────────────────────────────────


MOCK_API_KEY = "test-key-abc123"
TOGETHER_URL = "https://api.together.xyz/v1/chat/completions"
ANYSCALE_URL = "https://api.endpoints.anyscale.com/v1/chat/completions"


def _make_routes() -> list[RouteIndexEntry]:
    """Two route entries — minimum useful route map."""
    return [
        RouteIndexEntry(
            path="/api/users/1",
            methods=["GET"],
            auth_required=True,
            auth_stack="nextauth",
            file_path="app/api/users/[id]/route.ts",
            line=1,
        ),
        RouteIndexEntry(
            path="/api/posts/1",
            methods=["GET", "POST"],
            auth_required=True,
            auth_stack="nextauth",
            file_path="app/api/posts/[id]/route.ts",
            line=1,
        ),
    ]


def _make_responses() -> list[Response]:
    """Two observed responses, one a 403 to drive pivots."""
    return [
        Response(path="/api/users/1", method="GET", status=403, body="forbidden"),
        Response(path="/api/users/me", method="GET", status=200, body='{"id":1}'),
    ]


def _openai_chat_response(content: str, prompt_tokens: int = 100, completion_tokens: int = 50) -> dict:
    """Build a realistic OpenAI-compatible chat-completions body."""
    return {
        "id": "chatcmpl-abc123",
        "model": "meta-llama/Llama-3-70B-chat-hf",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


# ─── Test: System prompt has no guardrail language ────────────────────


class TestSystemPrompt:
    def test_no_guardrail_words(self):
        """System prompt must not prime the model to refuse.

        Words like "cannot", "illegal", "unethical" trip commercial-
        LLM guardrails and, more importantly, would make a permissive
        OSS model question its own output. The prompt frames the
        task positively (test coverage, permissions boundaries) and
        never invokes the refusal vocabulary.
        """
        lowered = SYSTEM_PROMPT.lower()
        for forbidden in ("cannot", "illegal", "unethical", "refuse", "harmful", "malicious"):
            assert forbidden not in lowered, (
                f"Guardrail word {forbidden!r} found in SYSTEM_PROMPT — "
                "would prime OSS model to refuse the task"
            )

    def test_includes_required_schema(self):
        """Prompt must include the JSON schema so the model emits parseable output."""
        assert "{curls:" in SYSTEM_PROMPT
        assert "method" in SYSTEM_PROMPT
        assert "path" in SYSTEM_PROMPT
        assert "intent" in SYSTEM_PROMPT

    def test_states_local_sandbox_context(self):
        """Prompt must anchor the model to the isolated test env."""
        assert "Firecracker" in SYSTEM_PROMPT
        assert "no egress" in SYSTEM_PROMPT.lower()


# ─── Test: Valid JSON response → FuzzPatterns ─────────────────────────


class TestGenerateValid:
    @pytest.mark.asyncio
    async def test_parses_valid_json_response(self):
        """Model returns pre-rendered curls → parsed into FuzzPatterns."""
        client = OSSInferenceClient(
            provider="together",
            api_key=MOCK_API_KEY,
            model="meta-llama/Llama-3-70B-chat-hf",
        )
        try:
            model_content = json.dumps(
                {
                    "curls": [
                        {
                            "curl": "curl -X GET http://sandbox/api/users/2 -H 'Authorization: Bearer tokenB'",
                            "intent": "bola_attempt",
                            "rationale": "Swap user_id 1→2 to test cross-tenant access",
                        },
                        {
                            "curl": "curl -X POST http://sandbox/api/users/1",
                            "intent": "method_swap",
                            "rationale": "POST on a GET-only resource may bypass auth",
                        },
                    ]
                }
            )
            with respx.mock(assert_all_called=True) as mock:
                mock.post(TOGETHER_URL).mock(
                    return_value=httpx.Response(
                        200, json=_openai_chat_response(model_content, 120, 80)
                    )
                )
                patterns = await client.generate(
                    route_map=_make_routes(),
                    observed_responses=_make_responses(),
                    remaining_budget=10,
                    sandbox_url="http://sandbox",
                )
            assert len(patterns) == 2
            assert all(isinstance(p, FuzzPattern) for p in patterns)
            assert patterns[0].intent == "bola_attempt"
            assert patterns[1].intent == "method_swap"
            assert patterns[0].rationalate if False else "cross-tenant" in patterns[0].rationale
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_renders_curl_when_model_emits_method_path_only(self):
        """Model returns method/path/headers (no pre-rendered curl) → we render it.

        OSS chat models are flakier than commercial ones about
        pre-rendering shell commands. The parser falls back to
        rendering from method/path/headers/body so a structurally-
        correct JSON still produces usable curls.
        """
        client = OSSInferenceClient(
            provider="together", api_key=MOCK_API_KEY,
        )
        try:
            model_content = json.dumps(
                {
                    "curls": [
                        {
                            "method": "GET",
                            "path": "/api/users/2",
                            "headers": {"Authorization": "Bearer tokenB"},
                            "intent": "bola_attempt",
                            "rationale": "cross-tenant ID swap",
                        }
                    ]
                }
            )
            with respx.mock() as mock:
                mock.post(TOGETHER_URL).mock(
                    return_value=httpx.Response(
                        200, json=_openai_chat_response(model_content, 100, 60)
                    )
                )
                patterns = await client.generate(
                    route_map=_make_routes(),
                    observed_responses=_make_responses(),
                    remaining_budget=10,
                    sandbox_url="http://sandbox:8080",
                )
            assert len(patterns) == 1
            curl = patterns[0].curl
            assert "curl" in curl
            assert "GET" in curl
            assert "http://sandbox:8080" in curl
            assert "/api/users/2" in curl
            assert "Authorization: Bearer tokenB" in curl
        finally:
            await client.aclose()


# ─── Test: Invalid JSON → graceful empty list ─────────────────────────


class TestGenerateInvalid:
    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty_list(self):
        """Model returns prose / garbage → no patterns, no crash."""
        client = OSSInferenceClient(
            provider="together", api_key=MOCK_API_KEY,
        )
        try:
            with respx.mock() as mock:
                # First attempt: garbage content. Retry sees same
                # garbage (respx mock repeats). Both attempts return
                # 200 with non-JSON content; the parser falls back
                # to regex, finds nothing, retries, then gives up.
                mock.post(TOGETHER_URL).mock(
                    return_value=httpx.Response(
                        200,
                        json=_openai_chat_response(
                            "I'm sorry, I can't help with that. "
                            "Please clarify your request.",
                            50,
                            20,
                        ),
                    )
                )
                patterns = await client.generate(
                    route_map=_make_routes(),
                    observed_responses=_make_responses(),
                    remaining_budget=10,
                    sandbox_url="http://sandbox",
                )
            assert patterns == []
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_markdown_fenced_json_still_parses(self):
        """Some OSS models wrap output in ```json ... ``` fences.

        The parser's regex fallback extracts the JSON from
        a single fenced block. This is a graceful-recovery
        test for a common model style.
        """
        client = OSSInferenceClient(
            provider="together", api_key=MOCK_API_KEY,
        )
        try:
            fenced = (
                "```json\n"
                + json.dumps(
                    {
                        "curls": [
                            {
                                "curl": "curl -X GET http://sandbox/api/users/2",
                                "intent": "bola_attempt",
                                "rationale": "x",
                            }
                        ]
                    }
                )
                + "\n```"
            )
            with respx.mock() as mock:
                mock.post(TOGETHER_URL).mock(
                    return_value=httpx.Response(
                        200, json=_openai_chat_response(fenced, 100, 60)
                    )
                )
                patterns = await client.generate(
                    route_map=_make_routes(),
                    observed_responses=_make_responses(),
                    remaining_budget=10,
                    sandbox_url="http://sandbox",
                )
            assert len(patterns) == 1
            assert patterns[0].intent == "bola_attempt"
        finally:
            await client.aclose()


# ─── Test: Rate limit → retry succeeds on 2nd attempt ────────────────


class TestRetry:
    @pytest.mark.asyncio
    async def test_rate_limit_retries_succeeds_on_second_attempt(self):
        """First call returns 429, second call returns valid JSON.

        Verifies the retry-with-jitter loop actually retries
        on 429 (not just on 5xx), and that a successful
        second attempt produces patterns. With respx, the
        first call returns 429 and the second returns 200;
        no `time.sleep` is needed because respx doesn't
        block on real time.
        """
        client = OSSInferenceClient(
            provider="together", api_key=MOCK_API_KEY,
        )
        try:
            model_content = json.dumps(
                {
                    "curls": [
                        {
                            "curl": "curl -X DELETE http://sandbox/api/users/2",
                            "intent": "method_swap",
                            "rationale": "DELETE on a GET-only resource",
                        }
                    ]
                }
            )
            with respx.mock() as mock:
                # First call: 429 rate limit. Second call: 200 OK.
                # `side_effect` makes the same route return
                # different responses on subsequent calls.
                route = mock.post(TOGETHER_URL).mock(
                    side_effect=[
                        httpx.Response(429, json={"error": "rate_limited"}),
                        httpx.Response(200, json=_openai_chat_response(model_content, 100, 40)),
                    ]
                )
                patterns = await client.generate(
                    route_map=_make_routes(),
                    observed_responses=_make_responses(),
                    remaining_budget=10,
                    sandbox_url="http://sandbox",
                )
            assert len(patterns) == 1
            assert patterns[0].intent == "method_swap"
            # The mock was hit exactly twice (one 429, one 200).
            assert route.call_count == 2
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_returns_empty(self):
        """Persistent 429 → empty list, no exception bubbled up.

        The orchestrator treats [] as "use rule-based patterns
        for this batch" and continues the scan. Raising an
        exception here would crash the Tier 3 chain.
        """
        client = OSSInferenceClient(
            provider="together", api_key=MOCK_API_KEY,
        )
        try:
            with respx.mock() as mock:
                # Both attempts: 429.
                mock.post(TOGETHER_URL).mock(
                    side_effect=[
                        httpx.Response(429, json={"error": "rate_limited"}),
                        httpx.Response(429, json={"error": "rate_limited"}),
                    ]
                )
                patterns = await client.generate(
                    route_map=_make_routes(),
                    observed_responses=_make_responses(),
                    remaining_budget=10,
                    sandbox_url="http://sandbox",
                )
            assert patterns == []
        finally:
            await client.aclose()


# ─── Test: Token count tracked ──────────────────────────────────────


class TestTokenTracking:
    @pytest.mark.asyncio
    async def test_tokens_accumulated_across_calls(self):
        """Two successful calls → tokens_in/tokens_out summed on `usage`."""
        client = OSSInferenceClient(
            provider="together", api_key=MOCK_API_KEY,
        )
        try:
            content = json.dumps(
                {
                    "curls": [
                        {
                            "curl": "curl -X GET http://sandbox/api/users/2",
                            "intent": "bola_attempt",
                            "rationale": "x",
                        }
                    ]
                }
            )
            with respx.mock() as mock:
                mock.post(TOGETHER_URL).mock(
                    side_effect=[
                        httpx.Response(200, json=_openai_chat_response(content, 100, 50)),
                        httpx.Response(200, json=_openai_chat_response(content, 200, 75)),
                    ]
                )
                await client.generate(
                    route_map=_make_routes(),
                    observed_responses=_make_responses(),
                    remaining_budget=10,
                    sandbox_url="http://sandbox",
                )
                await client.generate(
                    route_map=_make_routes(),
                    observed_responses=_make_responses(),
                    remaining_budget=10,
                    sandbox_url="http://sandbox",
                )
            assert client.usage.tokens_in == 300   # 100 + 200
            assert client.usage.tokens_out == 125  # 50 + 75
            assert client.usage.last_call_in == 200
            assert client.usage.last_call_out == 75
            assert client.usage.call_count == 2
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_token_usage_default_zero(self):
        """Fresh client has zero usage until a call completes."""
        client = OSSInferenceClient(
            provider="together", api_key=MOCK_API_KEY,
        )
        assert isinstance(client.usage, TokenUsage)
        assert client.usage.tokens_in == 0
        assert client.usage.tokens_out == 0
        assert client.usage.call_count == 0
        await client.aclose()


# ─── Test: No real LLM API calls ──────────────────────────────────────


class TestNoRealAPICall:
    @pytest.mark.asyncio
    async def test_no_real_api_call_without_respx(self):
        """Test isolation: nothing reaches the network unless respx mocks it.

        We use `respx.mock()` as a context manager. Outside of
        that block, the client's httpx transport would actually
        try to POST to api.together.xyz. The test wraps the
        call in respx.mock() (no routes registered) which
        intercepts ALL outbound calls and returns a 404. If
        the client tried to bypass respx (e.g. via a hardcoded
        raw socket), the test would hang on DNS resolution
        or fail with a connection error.

        This test runs `generate` under a `respx.mock()` with
        no registered routes; the mock will fail-fast on any
        unmocked call. We assert the call itself completes
        (with an empty-pattern result) — meaning all HTTP
        traffic was intercepted.
        """
        client = OSSInferenceClient(
            provider="together", api_key=MOCK_API_KEY,
        )
        try:
            with respx.mock(assert_all_mocked=False) as mock:
                # No routes registered. Without `assert_all_mocked=False`
                # respx would raise `AllMockedAssertionError` on the
                # first outbound request. We want the request to be
                # intercepted (it must not reach the real network) but
                # not raise. The client should treat the unmatched
                # request as a generic http_error and return [].
                patterns = await client.generate(
                    route_map=_make_routes(),
                    observed_responses=_make_responses(),
                    remaining_budget=10,
                    sandbox_url="http://sandbox",
                )
            # respx routes unmatched requests, so patterns is [].
            assert patterns == []
            # And the usage wasn't bumped (no successful call).
            assert client.usage.call_count == 0
        finally:
            await client.aclose()

    def test_does_not_import_commercial_llm_sdk(self):
        """OSS client must not import anthropic/openai SDKs.

        Importing the commercial SDKs would waste memory on
        the fuzz-agent worker and would risk accidentally
        calling the commercial LLM at runtime. The OSS
        path is httpx-only.
        """
        import importlib
        import sys

        # Force a fresh import — the module is already loaded
        # by the time this test runs, but `importlib.reload`
        # would re-execute it. We just check the module's
        # `__dict__` for any signs of the commercial SDKs.
        mod = sys.modules["sandbox.oss_inference"]
        mod_attrs = set(dir(mod))
        # anthropic / openai shouldn't appear as module-level
        # names. They could appear as TYPE_CHECKING imports,
        # but our module uses neither.
        assert "anthropic" not in mod_attrs
        assert "openai" not in mod_attrs


# ─── Test: Provider selection ────────────────────────────────────────


class TestProviderSelection:
    def test_together_endpoint(self):
        c = OSSInferenceClient(provider="together", api_key=MOCK_API_KEY)
        assert c.endpoint == "https://api.together.xyz/v1/chat/completions"
        assert c.provider == "together"

    def test_anyscale_endpoint(self):
        c = OSSInferenceClient(provider="anyscale", api_key=MOCK_API_KEY)
        assert c.endpoint == "https://api.endpoints.anyscale.com/v1/chat/completions"
        assert c.provider == "anyscale"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            OSSInferenceClient(provider="openai", api_key=MOCK_API_KEY)

    def test_missing_api_key_raises(self):
        with pytest.raises(ValueError, match="api_key is required"):
            OSSInferenceClient(provider="together", api_key="")

    @pytest.mark.asyncio
    async def test_anyscale_request_targets_anyscale_url(self):
        """Anyscale provider → POST to api.endpoints.anyscale.com, NOT together."""
        client = OSSInferenceClient(
            provider="anyscale", api_key=MOCK_API_KEY,
        )
        try:
            content = json.dumps({"curls": []})
            with respx.mock(assert_all_called=False) as mock:
                anyscale_route = mock.post(ANYSCALE_URL).mock(
                    return_value=httpx.Response(
                        200, json=_openai_chat_response(content, 50, 20)
                    )
                )
                together_route = mock.post(TOGETHER_URL).mock(
                    return_value=httpx.Response(200, json={"choices": [], "usage": {}})
                )
                await client.generate(
                    route_map=_make_routes(),
                    observed_responses=_make_responses(),
                    remaining_budget=10,
                    sandbox_url="http://sandbox",
                )
            assert anyscale_route.call_count == 1
            assert together_route.call_count == 0
        finally:
            await client.aclose()


# ─── Test: parser + validator unit tests ─────────────────────────────


class TestParseResponse:
    def test_valid_curls(self):
        text = json.dumps(
            {
                "curls": [
                    {
                        "curl": "curl -X GET http://s/x",
                        "intent": "bola_attempt",
                        "rationale": "x",
                    }
                ]
            }
        )
        out = _parse_response(text)
        assert len(out) == 1
        assert out[0].intent == "bola_attempt"

    def test_empty_curls(self):
        text = json.dumps({"curls": []})
        out = _parse_response(text)
        assert out == []

    def test_invalid_json_returns_empty(self):
        assert _parse_response("not json at all") == []

    def test_none_input_returns_empty(self):
        assert _parse_response("") == []
        assert _parse_response(None) == []

    def test_invalid_intent_coerced_to_default(self):
        """Unknown intent → bola_attempt, not dropped.

        The orchestrator can re-derive intent from path/method
        when it matters. Dropping the pattern would lose a
        valid curl.
        """
        text = json.dumps(
            {
                "curls": [
                    {
                        "curl": "curl -X GET http://s/x",
                        "intent": "totally-invented-intent",
                    }
                ]
            }
        )
        out = _parse_response(text)
        assert len(out) == 1
        assert out[0].intent == "bola_attempt"

    def test_missing_curl_field_drops_pattern(self):
        """A pattern without a curl field is useless — drop it."""
        text = json.dumps({"curls": [{"intent": "bola_attempt"}]})
        out = _parse_response(text)
        assert out == []


class TestValidatePattern:
    def test_valid(self):
        p = _validate_pattern({"curl": "curl -X GET /x", "intent": "bola_attempt"})
        assert p is not None
        assert p.curl == "curl -X GET /x"
        assert p.intent == "bola_attempt"

    def test_missing_curl_returns_none(self):
        assert _validate_pattern({"intent": "bola_attempt"}) is None

    def test_empty_curl_returns_none(self):
        assert _validate_pattern({"curl": "  ", "intent": "bola_attempt"}) is None

    def test_intent_coerced(self):
        p = _validate_pattern({"curl": "curl -X GET /x", "intent": "bogus"})
        assert p is not None
        assert p.intent == "bola_attempt"

    def test_rationale_clamped(self):
        p = _validate_pattern(
            {"curl": "curl -X GET /x", "intent": "bola_attempt", "rationale": "x" * 500}
        )
        assert p is not None
        assert len(p.rationale) == 200


class TestBuildCurl:
    def test_basic_get(self):
        out = _build_curl("GET", "/api/users/1", {}, None)
        assert "curl" in out
        assert "-X GET" in out
        assert "__SANDBOX_URL_PLACEHOLDER__" in out
        assert "/api/users/1" in out

    def test_with_headers(self):
        out = _build_curl("GET", "/x", {"Authorization": "Bearer t"}, None)
        assert "Authorization: Bearer t" in out

    def test_with_json_body(self):
        out = _build_curl("POST", "/x", {}, {"key": "value"})
        assert "--data-raw" in out
        assert "key" in out
        assert "value" in out

    def test_with_string_body(self):
        out = _build_curl("POST", "/x", {}, "raw body")
        assert "--data-raw" in out
        assert "raw body" in out
