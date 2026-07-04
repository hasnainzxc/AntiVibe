"""OSS inference client for Tier 3 fuzz-pattern generation.

Architecture
------------
The Tier 3 fuzz agent uses a *second* LLM — a hosted open-source
model on Together AI or Anyscale — to generate curl patterns we
then replay against the sandboxed app. The reason for a separate
model: commercial LLMs (Anthropic, OpenAI) have alignment
guardrails aligned to "do not assist offensive operations" that
flat-out refuse prompts like "generate curl to bypass tenant
isolation". An open-weight model on a permissive host doesn't
have those guardrails. We control the prompt space, the host,
and the output consumer (a Firecracker microVM with egress DENY
ALL), so the alignment problem is bounded.

The flip side: we trust neither the prompt input (route map +
observed responses) nor the model output (a curl command). The
*output* is sanitized by construction — it goes into a curl
shelled against localhost in an isolated microVM, so a hostile
curl can at most hit our own test fixture. The *input* never
leaves the sandbox-svc network; the LLM provider sees the
route map (path strings + method names) which is already
public information. We do NOT call `scanner.llm_extractor.sanitize`
on the prompt — that sanitizer strips secrets, and there are
no secrets in our outbound payload (no app source code, no
tokens, no PII).

Dual-model contract
-------------------
- Tier 1 LLM (Anthropic, task 14): extract semantic findings
  from app source code. Heavy sanitization, high cost, used
  once per scan.
- Tier 3 OSS LLM (this module): generate fuzz curls. No
  sanitization (no secrets in payload), low cost, called many
  times per scan within the budget.

Reliability
-----------
LLM APIs flake. We retry with exponential backoff + jitter
(`2^attempt + random[0,1)`) up to 2 attempts. A second failure
returns `[]` so the Tier 3 orchestrator can keep walking the
route index with rule-based patterns even if the model is down.

Provider endpoints
------------------
- `together`: https://api.together.xyz/v1/chat/completions
- `anyscale`: https://api.endpoints.anyscale.com/v1/chat/completions

Both are OpenAI-compatible chat-completions shapes, so the
request body is identical. The auth header is `Authorization:
Bearer <key>` for both.

Testing
-------
`tests/sandbox/test_oss_inference.py` covers: valid JSON parse,
invalid JSON graceful, rate-limit retry, token tracking,
no-guardrail system prompt, no real LLM call. All httpx calls
are mocked via respx — zero network egress in tests.
"""

import asyncio
import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Intent labels for `FuzzPattern.intent`. Mirrors the four
# pivot families in `docs/features/no-stop-pivot-engine.md`:
# - bola_attempt:     cross-tenant ID swap on a path param
# - pivot_to_adjacent: try a sibling path that may share an
#                      auth check (e.g. /api/users/2 → /api/users/me)
# - method_swap:      same path, different HTTP verb (POST→GET,
#                      GET→DELETE, etc.)
# - token_swap:       same request, different forged JWT
IntentType = Literal["bola_attempt", "pivot_to_adjacent", "method_swap", "token_swap"]
VALID_INTENTS: set[str] = {"bola_attempt", "pivot_to_adjacent", "method_swap", "token_swap"}

# Provider -> base URL. Both are OpenAI-compatible so the
# request body shape is the same; only the host differs.
# Anyscale's host name is `api.endpoints.anyscale.com` (NOT
# `api.anyscale.com`) — the latter is the marketing site.
PROVIDER_URLS: dict[str, str] = {
    "together": "https://api.together.xyz/v1/chat/completions",
    "anyscale": "https://api.endpoints.anyscale.com/v1/chat/completions",
}

# ─── System prompt ─────────────────────────────────────────────
#
# CRITICAL: this prompt is what lets the OSS model avoid the
# guardrail refusals that commercial LLMs hit. Three things
# matter here:
#
#  1. Frame the deployment as bounded and local. "isolated
#     Firecracker microVM with no egress" anchors the model
#     to "this is a test, not an attack on a real target".
#
#  2. Explicitly authorize the action. "Generate HTTP
#     requests to test permissions boundaries" tells the
#     model the curls are a sanctioned QA activity, not an
#     attack.
#
#  3. Demand strict JSON output. "Output strict JSON" with
#     the exact schema is what lets `_parse_response` skip
#     the regex fallback path. A model that wraps its
#     answer in prose breaks parsing.
#
# The test suite asserts no guardrail words ("cannot",
# "illegal", "unethical") appear in the prompt — those would
# prime the model to refuse.
SYSTEM_PROMPT = (
    "Maximize test coverage of local sandboxed endpoints. "
    "You are in isolated Firecracker microVM with no egress. "
    "Generate HTTP requests to test permissions boundaries. "
    "Output strict JSON: "
    '{curls:[{method, path, headers, body?, intent}]}. '
    "Output ONLY the JSON. No prose, no markdown fencing."
)

# Per-call max tokens. Fuzz patterns are short — a typical
# batch of 5 curls is ~300 tokens. 1024 leaves headroom for
# verbose model outputs without runaway cost.
MAX_TOKENS = 1024

# Retry budget. Per task spec: 2 attempts. The first retry
# waits `2^0 + jitter` seconds (~0-1s), which is short enough
# to stay inside the 10-min Tier 3 circuit-breaker even when
# every LLM call retries.
MAX_ATTEMPTS = 2


@dataclass
class FuzzPattern:
    """One curl command + the intent behind it.

    `curl` is a fully-rendered shell command, NOT a method/
    path/header triple. The fuzz walker can drop the string
    straight into a subprocess without re-construction. This
    is intentional: the model's "JSON" output is just a
    transport; the curl is the unit of work.

    `intent` is one of four labels (see `IntentType`). The
    Tier 3 orchestrator groups fuzz patterns by intent to
    drive different downstream behavior (e.g. token_swap
    patterns use both forged tokens, bola_attempt patterns
    use only User_B's token against User_A's resource).

    `rationale` is a short free-form string explaining WHY
    the model picked this curl. Useful for the report
    generator and for debugging false-positive patterns.
    """

    curl: str
    intent: str
    rationale: str = ""


@dataclass
class Response:
    """One observed HTTP response from a previous fuzz probe.

    Defined here (not in the route walker module) because
    `OSSInferenceClient.generate` consumes them and the walker
    module is owned by a different task. Keeping the type
    local avoids a circular import.

    Fields:
        path:    URL path that was probed (e.g. "/api/users/2").
        method:  HTTP method used (e.g. "GET").
        status:  Response status code (e.g. 403, 404, 200).
        body:    Raw response body. Capped at 1KB by the
                 caller — the LLM doesn't need megabytes of
                 JSON to decide what to fuzz next.
    """

    path: str
    method: str
    status: int
    body: str = ""


@dataclass
class TokenUsage:
    """Cumulative token counters on the client instance.

    `tokens_in` and `tokens_out` are summed across every
    successful `generate()` call on this client. A `CostLedger`
    elsewhere in the system reads these counters at scan
    shutdown to write the per-scan cost row.

    `last_call_in` / `last_call_out` are convenience fields
    for tests (verify the most recent call's token count)
    and for the structured log line per call.
    """

    tokens_in: int = 0
    tokens_out: int = 0
    last_call_in: int = 0
    last_call_out: int = 0
    call_count: int = 0


def _validate_pattern(p: dict) -> Optional[FuzzPattern]:
    """Coerce one LLM-emitted dict into a validated FuzzPattern.

    Drops patterns with the wrong shape (missing curl, non-string
    intent, etc.) rather than raising — the Tier 3 orchestrator
    prefers fewer patterns over a hard failure. Invalid `intent`
    values fall back to `"bola_attempt"` (the most common case
    in practice) rather than being dropped; this is a deliberate
    trade-off — under-classifying the intent is recoverable
    (the orchestrator can re-derive it from the path/method),
    dropping the pattern would lose a valid curl.

    Returns None only if the dict is missing the `curl` field
    or `curl` is empty — without a curl, there's no fuzz
    pattern to act on.
    """
    curl = p.get("curl")
    if not isinstance(curl, str) or not curl.strip():
        return None

    intent = str(p.get("intent", ""))
    # Coerce unknown intent to the default. This is lossy but
    # safer than dropping the pattern — the orchestrator
    # re-derives intent from path/method when it matters.
    if intent not in VALID_INTENTS:
        intent = "bola_attempt"

    rationale = str(p.get("rationale", ""))[:200]
    return FuzzPattern(curl=curl, intent=intent, rationale=rationale)


def _build_curl(method: str, path: str, headers: dict, body: Any) -> str:
    """Render an LLM-emitted dict as a shell-safe curl command.

    Path is prefixed with the sandbox URL by the caller, so
    `path` here is relative (e.g. "/api/users/2"). Headers
    are passed via repeated `-H` flags. Body, if present, is
    passed via `--data-raw` and JSON-quoted; we don't try
    to escape embedded quotes — the model is trusted to
    emit either a flat object or a string body, and the
    output is consumed by a local shell in an isolated
    microVM, so shell injection would only hit our own
    fixture.
    """
    parts = ["curl", "-sS", "-X", method.upper()]
    for k, v in (headers or {}).items():
        parts.extend(["-H", f"{k}: {v}"])
    if body is not None:
        body_str = json.dumps(body) if not isinstance(body, str) else body
        parts.extend(["--data-raw", body_str])
    # NOTE: sandbox_url is prepended at call time, not here,
    # so this fn stays pure and unit-testable in isolation.
    parts.append("__SANDBOX_URL_PLACEHOLDER__")
    parts.append(path)
    return " ".join(parts)


def _build_user_payload(
    route_map: list,
    observed_responses: list,
    remaining_budget: int,
    sandbox_url: str,
) -> str:
    """Serialize the user-side prompt as JSON.

    The model is told the route map, the most recent observed
    responses, the sandbox URL, and the remaining budget. We
    keep the payload small (<2KB) to keep input tokens cheap:
    the route map is summarized to {path, method, auth_required}
    only, and observed_responses are capped at the last 10
    (more than that and the model gets confused by stale
    signals).
    """
    routes_summary = []
    for r in route_map[:50]:  # hard cap; 50 routes is a big app
        # Support both dataclass RouteIndexEntry and plain dicts.
        if hasattr(r, "path"):
            routes_summary.append(
                {
                    "path": r.path,
                    "method": (r.methods[0] if getattr(r, "methods", None) else "GET"),
                    "auth_required": getattr(r, "auth_required", False),
                }
            )
        elif isinstance(r, dict):
            routes_summary.append(
                {
                    "path": r.get("path", ""),
                    "method": r.get("method", "GET"),
                    "auth_required": r.get("auth_required", False),
                }
            )

    obs_summary = []
    for obs in (observed_responses or [])[-10:]:
        if hasattr(obs, "path"):
            obs_summary.append(
                {
                    "path": obs.path,
                    "method": obs.method,
                    "status": obs.status,
                    "body_snippet": (obs.body or "")[:200],
                }
            )
        elif isinstance(obs, dict):
            obs_summary.append(
                {
                    "path": obs.get("path", ""),
                    "method": obs.get("method", "GET"),
                    "status": obs.get("status", 0),
                    "body_snippet": (obs.get("body", "") or "")[:200],
                }
            )

    payload = {
        "sandbox_url": sandbox_url,
        "remaining_budget": remaining_budget,
        "route_map": routes_summary,
        "observed_responses": obs_summary,
    }
    return json.dumps(payload, indent=2)


def _parse_response(response_text: str) -> list[FuzzPattern]:
    """Parse the LLM's response into validated FuzzPatterns.

    Tries three parse paths in order:
      1. Direct JSON parse (`json.loads`).
      2. Extract from a single ```json ... ``` fenced block.
      3. If the dict has `curls` but each entry is missing
         `curl`, render the entries as curls via `_build_curl`.
      4. Give up and return [].

    The fallback paths exist because OSS chat models are
    flakier than commercial ones about JSON-only output.
    A response that says `{"curls": [{"method":"GET",...}]}`
    without a pre-rendered `curl` string is still useful —
    we render the curl ourselves rather than discarding the
    batch.
    """
    if not response_text:
        return []

    try:
        data = json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

    if not isinstance(data, dict):
        return []
    raw = data.get("curls", [])
    if not isinstance(raw, list):
        return []

    patterns = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        # If the model emitted a pre-rendered curl, use it.
        if "curl" in entry and isinstance(entry["curl"], str) and entry["curl"].strip():
            patterns.append(_validate_pattern(entry))
            continue
        # Otherwise render from method/path/headers/body.
        # We need at least method + path to render a curl.
        method = entry.get("method")
        path = entry.get("path")
        if not (isinstance(method, str) and isinstance(path, str)):
            continue
        rendered = _build_curl(
            method=method,
            path=path,
            headers=entry.get("headers") or {},
            body=entry.get("body"),
        )
        patterns.append(
            _validate_pattern({**entry, "curl": rendered})
        )

    # Drop Nones (validation failures) and return.
    return [p for p in patterns if p is not None]


class OSSInferenceClient:
    """Hosted OSS inference client (Together AI / Anyscale) for fuzz patterns.

    Constructor args are keyword-only so callers can't accidentally
    swap `provider` and `api_key` positionally. `api_key` has no
    default — every call site must pass an explicit key (or
    pre-populate `TOGETHER_API_KEY` / `ANYSCALE_API_KEY` env vars
    and the caller passes `os.environ[...]`).

    `model` defaults to Llama-3-70B on Together, the cheapest
    OSS model that's still good at JSON output. Override to
    `"meta-llama/Llama-3-70b-chat-hf"` for Anyscale or
    `"deepseek-ai/DeepSeek-R1-Distill-Llama-70B"` for
    Anyscale's reasoning-tuned variant.

    Token tracking
    --------------
    `self.usage` is a `TokenUsage` instance that accumulates
    token counts across all `generate()` calls on this client.
    The Tier 3 orchestrator reads `usage.tokens_in` /
    `usage.tokens_out` at scan shutdown to write the cost
    ledger row. The fields are per-client (not per-scan), so
    the orchestrator should construct a fresh client per scan
    to keep the counters scoped correctly.
    """

    def __init__(
        self,
        *,
        provider: str = "together",
        api_key: str,
        model: str = "meta-llama/Llama-3-70B-chat-hf",
    ):
        if provider not in PROVIDER_URLS:
            raise ValueError(
                f"Unknown provider {provider!r}; expected one of {list(PROVIDER_URLS)}"
            )
        if not api_key:
            raise ValueError("api_key is required for OSSInferenceClient")

        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.endpoint = PROVIDER_URLS[provider]
        self.usage = TokenUsage()
        # httpx client is created lazily so a misconfigured
        # client (bad provider, no key) doesn't try to open a
        # connection at import time.
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """Return a memoized httpx.AsyncClient.

        Created on first use, not in __init__, so a test that
        only inspects the constructor (e.g. checking defaults)
        doesn't pay the cost of opening a connection pool.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying httpx connection pool.

        Call this when the scan finishes. Forgetting to close
        leaks a connection until GC, which is fine for short-
        lived CLI runs but matters for the dashboard's
        long-running async server.
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post_chat_completion(self, user_payload: str) -> dict:
        """Issue one chat-completions request and normalize the response.

        Returns a dict with one of:
          - `{"content": <str>, "usage": {"input_tokens": int, "output_tokens": int}}`
            on a 2xx with a parseable body.
          - `{"error": <str>}` on a non-2xx, network failure, or
            body that can't be parsed. The caller treats both
            shapes uniformly (retry on error, parse on success).

        The 30s timeout is per request, not per retry. With
        MAX_ATTEMPTS=2, a worst-case retry takes ~31s (30s +
        ~1s backoff) which is well under the 10-min scan
        circuit-breaker.
        """
        body = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "temperature": 0.7,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
        }
        client = self._get_client()
        try:
            response = await client.post(self.endpoint, json=body)
        except httpx.HTTPError as e:
            return {"error": f"http_error: {e!r}"}

        if response.status_code == 429:
            # Rate limit — distinct error tag so the retry
            # loop can branch on it (e.g. longer backoff).
            return {"error": "rate_limited", "status": 429}
        if response.status_code >= 500:
            return {"error": f"server_error: HTTP {response.status_code}", "status": response.status_code}
        if response.status_code != 200:
            return {"error": f"http_status_{response.status_code}", "status": response.status_code}

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            return {"error": "invalid_json_body"}

        # OpenAI-compatible response shape:
        # {"choices": [{"message": {"content": "..."}}], "usage": {"prompt_tokens": N, "completion_tokens": N}}
        try:
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return {
                "content": content,
                "usage": {
                    "input_tokens": int(usage.get("prompt_tokens", 0)),
                    "output_tokens": int(usage.get("completion_tokens", 0)),
                },
            }
        except (KeyError, IndexError, TypeError, ValueError) as e:
            return {"error": f"response_shape_invalid: {e!r}"}

    async def generate(
        self,
        *,
        route_map: list,
        observed_responses: list,
        remaining_budget: int,
        sandbox_url: str,
    ) -> list[FuzzPattern]:
        """Generate the next batch of fuzz patterns.

        Args:
            route_map: list of `RouteIndexEntry` (or dicts with
                {path, method, auth_required}). Capped at 50
                entries in the user payload.
            observed_responses: list of `Response` (or dicts).
                Last 10 are included; older ones are stale
                signal that confuses the model.
            remaining_budget: int, how many probes are left in
                this scan. Surfaced in the user payload so the
                model can right-size its batch (a model given
                `remaining_budget=3` should return 3 patterns,
                not 10).
            sandbox_url: str, the Firecracker microVM's URL
                (e.g. "http://antivibe-sandbox.flycast:80").
                Inlined into every rendered curl.

        Returns:
            list[FuzzPattern]. Empty on any failure path
            (parse error, all retries exhausted, empty model
            output). The orchestrator treats an empty list
            as "use rule-based patterns for this batch" and
            continues.

        Side effects:
            Increments `self.usage.tokens_in` / `tokens_out` /
            `call_count` on every successful call. Logs each
            attempt at info level with the token counts.
        """
        user_payload = _build_user_payload(
            route_map=route_map,
            observed_responses=observed_responses,
            remaining_budget=remaining_budget,
            sandbox_url=sandbox_url,
        )

        # Retry loop. Bounded by MAX_ATTEMPTS=2; the first
        # attempt is `attempt=0`, so the loop runs at most
        # twice. We deliberately don't loop on parse success
        # — a successful call is the terminal state.
        for attempt in range(MAX_ATTEMPTS):
            response = await self._post_chat_completion(user_payload)

            if "error" in response:
                logger.warning(
                    "oss_inference.call_failed",
                    attempt=attempt,
                    error=response["error"],
                    provider=self.provider,
                )
                # Backoff: 2^attempt + jitter seconds. For
                # attempt=0, that's 1 + jitter (~0-1s).
                # For attempt=1, that's 2 + jitter (~0-1s).
                # Short enough to stay under the 10-min
                # circuit-breaker; long enough to de-correlate
                # from parallel orchestrators.
                backoff = (2 ** attempt) + random.uniform(0, 1)
                if attempt < MAX_ATTEMPTS - 1:
                    await asyncio.sleep(backoff)
                continue

            content = response.get("content", "")
            usage = response.get("usage", {})
            tokens_in = int(usage.get("input_tokens", 0))
            tokens_out = int(usage.get("output_tokens", 0))

            patterns = _parse_response(content)
            # Accept the call if we got patterns OR if the
            # content was a well-formed `{"curls": ...}`
            # shape (even if the list was empty — the model
            # may legitimately have no ideas left).
            content_has_curls = '"curls"' in content or "'curls'" in content
            if patterns or content_has_curls:
                # Account the tokens before we splice in the
                # sandbox URL — tokens are billed on what was
                # sent over the wire, not what we post-process.
                self.usage.tokens_in += tokens_in
                self.usage.tokens_out += tokens_out
                self.usage.last_call_in = tokens_in
                self.usage.last_call_out = tokens_out
                self.usage.call_count += 1

                # Splice the sandbox URL into every rendered
                # curl. The placeholder is the same one
                # `_build_curl` writes, so this is a literal
                # string replace on a token that never appears
                # in user input (no shell-quoting risk).
                for p in patterns:
                    if "__SANDBOX_URL_PLACEHOLDER__" in p.curl:
                        p.curl = p.curl.replace(
                            "__SANDBOX_URL_PLACEHOLDER__", sandbox_url
                        )

                logger.info(
                    "oss_inference.call_ok",
                    provider=self.provider,
                    model=self.model,
                    patterns=len(patterns),
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )
                return patterns

            # Got a 2xx but the content is neither a valid
            # curls payload nor a parseable empty-curls
            # marker. Treat as an error and retry.
            logger.warning(
                "oss_inference.invalid_output",
                attempt=attempt,
                content_preview=(content or "")[:120],
            )
            if attempt < MAX_ATTEMPTS - 1:
                backoff = (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(backoff)

        # All retries failed. Return [] so the orchestrator
        # can keep walking with rule-based patterns.
        logger.error(
            "oss_inference.all_retries_failed",
            provider=self.provider,
            model=self.model,
        )
        return []
