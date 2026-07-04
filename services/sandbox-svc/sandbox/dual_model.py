"""Dual-model orchestrator for Tier 3 fuzz agent.

Architecture
------------
This module is the *brain* of the Tier 3 fuzz agent. It coordinates
two LLMs on the same scan:

  1. **Commercial LLM** (Anthropic Claude via `LLMClient`) — used
     ONCE at the end of the scan to summarize observed responses
     into structured `LLMFinding` objects. Heavy sanitization,
     high cost, used sparingly.

  2. **OSS hosted inference** (Together / Anyscale via
     `OSSInferenceClient`) — used in a tight loop to generate
     fuzz-pattern curls. No sanitization (no secrets in payload),
     low cost, called many times within a `budget` cap.

The two models serve different roles. The commercial model has
guardrails that flat-out refuse prompts like "generate curl to
bypass tenant isolation" — that's why we use an open-weight
model for fuzz-pattern generation. The commercial model is
still useful for *summarization*: given a list of observed
HTTP responses, it can identify which ones look like real BOLA
exploits vs. incidental 200s. This is a benign QA framing
("identify access-control logic flaws in the provided code"
— same system prompt as Tier 1) that the commercial model is
happy to answer.

The loop
--------
1. Ask the OSS fuzzer for a batch of `FuzzPattern`s.
2. Fire each pattern's curl at the sandbox; collect `Response`s.
3. After every `BATCH_REFETCH_EVERY` probes, feed the new
   observations back to the OSS fuzzer and ask for the next
   batch.
4. Stop on one of:
     - `exhausted_avenues`: OSS returns `[]` or every pattern
       has `intent="none"`. The model is signaling "I've run
       out of ideas worth testing".
     - `budget_exhausted`: the `budget` cap (default 200) is
       hit. The loop never overruns regardless of OSS output.
5. At loop end, summarize all observed responses via the
   commercial LLM. Yield each `LLMFinding` to the caller.

Why an async iterator
---------------------
`iterate()` is an `AsyncIterator[LLMFinding]` so the caller
gets a stream of confirmed findings as the scan progresses.
The commercial summary happens at the END of the loop, so
all findings are yielded after the fuzz loop completes —
but the iterator API lets a future `tier3_orchestrator`
change the emission point without changing the contract.

Why shlex, not subprocess
-------------------------
We could shell out `curl` via `asyncio.create_subprocess_exec`,
but that needs the binary in the sandbox-svc image AND it
invokes a real process tree on every probe (200+ per scan).
`shlex.split` + `httpx` parses the curl and issues the
request in-process — same network shape, half the moving
parts. The `FuzzPattern.curl` strings are produced by
`_build_curl` in `oss_inference.py`, so the parse rules
are bounded and testable.

Reliability
-----------
The OSS fuzzer is unreliable (rate limits, model flakes,
JSON parse failures). The orchestrator treats an empty
`[]` return as the exhausted-avenues signal and stops
the loop. The commercial extractor is called exactly
once at the end; on extractor failure, the iterator
yields no findings rather than raising — a partial scan
is more useful than a hard crash.

Dependency map
--------------
- Reads from: `scanner.llm_extractor.LLMClient`,
              `sandbox.oss_inference.OSSInferenceClient`,
              `sandbox.jwt_forge.ForgedToken`,
              `sandbox.route_mapper.RouteIndexEntry`.
- Writes to: nothing; yields `LLMFinding` to the caller.
- Consumed by: the Tier 3 orchestrator (task 29).

Testing
-------
`tests/sandbox/test_dual_model.py` covers: full loop w/
mock fuzzer, exhausted_avenues stop, budget cap stop,
token accumulation (both OSS + commercial), and no real
LLM egress. The fuzzer and extractor are mocks; the
httpx client is an `AsyncMock`. No real network in any
test.
"""

import shlex
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import structlog

from sandbox.jwt_forge import ForgedToken
from sandbox.oss_inference import FuzzPattern, OSSInferenceClient, Response
from scanner.llm_extractor import (
    SYSTEM_PROMPT as _EXTRACTOR_SYSTEM_PROMPT,
)
from scanner.llm_extractor import (
    LLMClient,
    LLMFinding,
)
from scanner.llm_extractor import (
    _parse_response as _parse_extractor_response,
)

logger = structlog.get_logger(__name__)


# Re-use the Tier 1 extractor system prompt. The commercial
# model is good at identifying access-control flaws in arbitrary
# input, not just source code. The framing in the prompt ("You
# are a security code reader") is loose enough that a list of
# observed HTTP responses is a valid input shape.
_SUMMARY_PROMPT = _EXTRACTOR_SYSTEM_PROMPT


# Probes fired between OSS refetch calls. The model output is
# best when given fresh observed responses, but every OSS call
# costs ~200ms of round-trip. 5 is the balance: enough signal
# for the model to pivot on, few enough to keep the scan
# under 30s end-to-end. The number is also small enough that a
# single batch (5 patterns) keeps memory bounded.
BATCH_REFETCH_EVERY = 5


# Cap response bodies in the observation buffer. The LLM only
# needs ~200 chars of body to decide what to pivot on; keeping
# bodies small caps memory and token cost. 1KB matches the
# 1KB cap in `oss_inference.Response.body` (set by callers).
MAX_RESPONSE_BODY_CHARS = 1024


# Default per-scan probe cap. Matches the route-walker's
# `max_attempts` default. Hard stop — the loop never exceeds
# this regardless of OSS output.
DEFAULT_BUDGET = 200


# Default httpx timeout per probe. 10s is generous for a local
# Firecracker microVM; a hung probe would just hit the
# circuit-breaker eventually.
PROBE_TIMEOUT_S = 10.0


# Sentinel pattern.intent value for the exhausted-avenues
# signal. The OSS model returns a normal pattern dict but
# sets `intent="none"` to mean "I've run out of ideas".
# This is NOT in `VALID_INTENTS` (which has the four pivot
# families), so a `_validate_pattern` call would coerce
# it to "bola_attempt" — we therefore check for "none"
# BEFORE letting validation see the pattern.
EXHAUSTED_INTENT = "none"


@dataclass
class TokenLedger:
    """Per-scan token counters.

    Two separate buckets because the cost model differs:
    OSS tokens are ~10x cheaper than commercial. The
    dashboard renders them as a stacked bar in the cost
    summary, so keeping them separate at this layer avoids
    a re-derivation at render time.
    """

    oss_in: int = 0
    oss_out: int = 0
    commercial_in: int = 0
    commercial_out: int = 0

    def total(self) -> int:
        return self.oss_in + self.oss_out + self.commercial_in + self.commercial_out


def _parse_curl(curl_str: str) -> tuple[str, str, dict, str | None]:
    """Parse a curl command string into (method, url, headers, body).

    The expected shape is what `_build_curl` produces in
    `oss_inference.py`:

        curl -sS -X METHOD -H "K: V" [--data-raw BODY] URL PATH

    Returns ("GET", "", {}, None) on parse failure. Empty
    URL signals the caller to skip the probe (it's a
    malformed pattern, not a transport error).

    `shlex` handles the quoted `-H "K: V"` form; the URL
    + PATH concatenation is handled by joining consecutive
    non-flag tokens. A well-formed curl from our own
    builder has at most 2 non-flag tokens (base URL +
    path), so the join is bounded.
    """
    try:
        parts = shlex.split(curl_str)
    except ValueError:
        return "GET", "", {}, None
    if not parts or parts[0] != "curl":
        return "GET", "", {}, None

    method = "GET"
    headers: dict = {}
    body: str | None = None
    url_tokens: list[str] = []

    i = 1
    while i < len(parts):
        p = parts[i]
        if p in ("-X", "--request"):
            method = parts[i + 1].upper() if i + 1 < len(parts) else "GET"
            i += 2
        elif p in ("-H", "--header"):
            if i + 1 < len(parts):
                kv = parts[i + 1]
                if ":" in kv:
                    k, v = kv.split(":", 1)
                    headers[k.strip()] = v.strip()
            i += 2
        elif p in ("-d", "--data", "--data-raw", "--data-binary"):
            if i + 1 < len(parts):
                body = parts[i + 1]
            i += 2
        elif p in ("-sS", "-s", "-S", "-i", "-L", "-k", "--insecure"):
            # `-sS` is `-s -S` (silent + show errors). We
            # accept the bundle form; either way it's a
            # no-op for our purposes.
            i += 1
        elif p.startswith("-"):
            # Unknown flag — skip. We don't try to be smart
            # about flag-with-value shapes because we
            # control the curl builder.
            i += 1
        else:
            url_tokens.append(p)
            i += 1

    url = "".join(url_tokens)
    return method, url, headers, body


def _serialize_observations(
    observed: list[Response],
    route_map: list,
    sandbox_url: str,
    tokens: tuple[ForgedToken, ForgedToken],
) -> str:
    """Render the observation buffer as a single user-prompt string.

    The commercial LLM gets a compact summary — not the raw
    200-response buffer. We cap the route map at 50 entries
    and the observation tail at 50, which keeps the prompt
    under ~3KB even on a busy scan. Headers and JWTs are
    included in the route map section (so the model sees the
    auth shape) but truncated in the response section (where
    a long body is just noise).
    """
    lines: list[str] = [f"# Sandbox: {sandbox_url}", ""]
    lines.append("## Forged tokens (cross-tenant pivots):")
    for t in tokens:
        lines.append(f"  - {t.user_id} (tenant {t.tenant_id}, role {t.role})")
    lines.append("")
    lines.append(f"## Route map ({min(50, len(route_map))} shown):")
    for r in route_map[:50]:
        if hasattr(r, "path"):
            path = r.path
            methods = getattr(r, "methods", ["GET"]) or ["GET"]
            method = methods[0] if methods else "GET"
        elif isinstance(r, dict):
            path = r.get("path", "")
            method = r.get("method", "GET")
        else:
            continue
        lines.append(f"  - {method} {path}")
    lines.append("")
    lines.append(
        f"## Observed responses ({len(observed)} total, last 50 shown):"
    )
    for obs in observed[-50:]:
        if hasattr(obs, "path"):
            path = obs.path
            method = obs.method
            status = obs.status
            body = (obs.body or "")[:200]
        elif isinstance(obs, dict):
            path = obs.get("path", "")
            method = obs.get("method", "GET")
            status = obs.get("status", 0)
            body = (obs.get("body", "") or "")[:200]
        else:
            continue
        lines.append(f"  - {method} {path} -> {status}: {body}")
    return "\n".join(lines)


class DualModelOrchestrator:
    """Coordinates the OSS fuzzer (loop) and commercial extractor (summary).

    Args:
        extractor: `LLMClient` for the commercial model. Called
            exactly once at the end of `iterate()` to summarize
            observations into `LLMFinding` objects.
        fuzzer: `OSSInferenceClient` for the OSS hosted model.
            Called in a tight loop to generate fuzz-pattern curls.
        http_client: optional pre-configured `httpx.AsyncClient`.
            If None, a default client is created lazily. Tests
            inject an `AsyncMock` to avoid real network egress.

    Attributes:
        tokens_used: `TokenLedger` accumulating token counts
            across both models. Read by the cost ledger at
            scan shutdown.
    """

    def __init__(
        self,
        *,
        extractor: LLMClient,
        fuzzer: OSSInferenceClient,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.extractor = extractor
        self.fuzzer = fuzzer
        self._http = http_client
        self._owns_http = http_client is None
        self.tokens_used = TokenLedger()

    def _get_http(self) -> httpx.AsyncClient:
        """Return the http client, creating it lazily if we own it."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(PROBE_TIMEOUT_S, connect=5.0),
            )
        return self._http

    async def aclose(self) -> None:
        """Close the underlying httpx client if we own it.

        The OSS fuzzer owns its own client (created in
        `OSSInferenceClient.__init__`'s lazy init). The
        commercial extractor is the Anthropic SDK's client
        (owned by `LLMClient`). The only client we own is
        the http_client created by `_get_http()`.
        """
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _fire_pattern(
        self, pattern: FuzzPattern, sandbox_url: str
    ) -> Response:
        """Execute one FuzzPattern's curl against the sandbox.

        Parses the curl into httpx args, fires the request,
        and returns a normalized `Response`. On any error
        (parse failure, network failure, timeout), returns
        a synthetic `Response` with `status=0` and a short
        error string in `body`. The 0-status is a sentinel
        the summary LLM can recognize as "transport error,
        not a real HTTP response".
        """
        method, url, headers, body = _parse_curl(pattern.curl)
        if not url:
            return Response(
                path=pattern.curl[:200],
                method=method or "GET",
                status=0,
                body="parse_error",
            )

        client = self._get_http()
        try:
            if body is not None:
                response = await client.request(
                    method, url, headers=headers, content=body
                )
            else:
                response = await client.request(
                    method, url, headers=headers
                )
            body_text = (response.text or "")[:MAX_RESPONSE_BODY_CHARS]
            return Response(
                path=url,
                method=method,
                status=response.status_code,
                body=body_text,
            )
        except httpx.HTTPError as e:
            return Response(
                path=url,
                method=method,
                status=0,
                body=f"http_error: {e!r}",
            )

    async def _summarize_with_extractor(
        self,
        observed: list[Response],
        route_map: list,
        sandbox_url: str,
        tokens: tuple[ForgedToken, ForgedToken],
    ) -> list[LLMFinding]:
        """Call the commercial LLM to summarize observations.

        Builds a compact prompt from the observation buffer,
        routes it through `LLMClient.complete()` (the same
        API Tier 1 uses), parses the response, and validates
        each finding. Token counts are added to
        `self.tokens_used` regardless of parse outcome.

        Returns an empty list on any error (extractor
        missing, API failure, unparseable response).
        Partial scans are more useful than hard crashes —
        the caller can still write a report from the
        observation buffer.
        """
        summary = _serialize_observations(
            observed, route_map, sandbox_url, tokens
        )

        try:
            response = self.extractor.complete(_SUMMARY_PROMPT, summary)
        except Exception as e:
            logger.warning("dual_model.extractor_exception", error=str(e))
            return []

        if not isinstance(response, dict) or "error" in response:
            err = (
                response.get("error")
                if isinstance(response, dict)
                else "bad_response_shape"
            )
            logger.warning("dual_model.extractor_error", error=err)
            return []

        content = response.get("content", "")
        usage = response.get("usage", {})
        try:
            tokens_in = int(usage.get("input_tokens", 0))
            tokens_out = int(usage.get("output_tokens", 0))
        except (TypeError, ValueError):
            tokens_in = 0
            tokens_out = 0

        self.tokens_used.commercial_in += tokens_in
        self.tokens_used.commercial_out += tokens_out

        model_name = getattr(self.extractor, "model", "claude-3-5-sonnet")
        # _parse_extractor_response already returns LLMFinding
        # (it does its own _validate_finding internally);
        # re-validating here would treat a Finding as a dict
        # and crash on `f.get(...)`.
        findings: list[LLMFinding] = []
        for parsed in _parse_extractor_response(content):
            parsed.tokens_in = tokens_in
            parsed.tokens_out = tokens_out
            parsed.model = model_name
            findings.append(parsed)
        return findings

    async def iterate(
        self,
        *,
        route_map: list,
        sandbox_url: str,
        tokens: tuple[ForgedToken, ForgedToken],
        budget: int = DEFAULT_BUDGET,
    ) -> AsyncIterator[LLMFinding]:
        """Run the dual-model loop and yield confirmed findings.

        The loop:

            1. Fetch a batch of `FuzzPattern`s from the OSS fuzzer.
            2. Fire each pattern's curl at the sandbox.
            3. Every `BATCH_REFETCH_EVERY` probes, refetch the
               next batch (feeding observed responses back).
            4. Stop on `exhausted_avenues` (empty batch or all
               `intent="none"`) or `budget` exhausted.
            5. On stop, call the commercial extractor to summarize.
            6. Yield each `LLMFinding` from the summary.

        Args:
            route_map: `list[RouteIndexEntry]` from the route
                mapper. Passed to the OSS fuzzer's prompt.
            sandbox_url: `str` — the Firecracker microVM's URL.
                Prepended to every curl by the OSS fuzzer.
            tokens: `(token_a, token_b)` from `jwt_forge.forge()`.
                Embedded in the summary prompt so the commercial
                model knows the cross-tenant pivot identities.
            budget: `int` — total probe cap. Hard stop. Default
                200 (matches the route-walker cap).

        Yields:
            `LLMFinding` instances from the commercial summary.
            On extractor failure, yields nothing.

        Side effects:
            Increments `self.tokens_used` for both models.
            Issues HTTP probes to `sandbox_url` via the
            (mockable) http client.
        """
        observed: list[Response] = []
        probes_fired = 0
        stop_reason = "exhausted_avenues"

        # Snapshot OSS usage before we start. The fuzzer is
        # shared state — its `usage` counter may have prior
        # calls if the caller reused a client (which they
        # shouldn't, but defensive code is cheap).
        oss_in_before = self.fuzzer.usage.tokens_in
        oss_out_before = self.fuzzer.usage.tokens_out

        # First batch. If this is empty or all "none", we
        # never enter the loop body — `while batch` is False.
        batch: list[FuzzPattern] = await self.fuzzer.generate(
            route_map=route_map,
            observed_responses=observed,
            remaining_budget=max(0, budget - probes_fired),
            sandbox_url=sandbox_url,
        )

        while batch and probes_fired < budget:
            # Check exhausted_avenues: every pattern is
            # `intent="none"` (empty list is already gated
            # by `while batch`).
            if all(p.intent == EXHAUSTED_INTENT for p in batch):
                stop_reason = "exhausted_avenues"
                break

            # Fire this batch. We break out of the inner
            # for-loop on budget exhaustion OR after
            # BATCH_REFETCH_EVERY probes (whichever comes
            # first), then refetch.
            for pattern in batch:
                if probes_fired >= budget:
                    stop_reason = "budget"
                    break
                # Defensive skip: a mixed batch with some
                # "none" patterns should not fire the
                # "none" ones (they have no real curl to
                # execute against the real sandbox).
                if pattern.intent == EXHAUSTED_INTENT:
                    continue
                resp = await self._fire_pattern(pattern, sandbox_url)
                observed.append(resp)
                probes_fired += 1
                if probes_fired % BATCH_REFETCH_EVERY == 0:
                    break

            if probes_fired >= budget:
                stop_reason = "budget"
                break

            # Refetch next batch (with observed responses
            # as feedback). If the new batch is empty,
            # the while-loop exits and stop_reason stays
            # as "exhausted_avenues".
            batch = await self.fuzzer.generate(
                route_map=route_map,
                observed_responses=observed,
                remaining_budget=max(0, budget - probes_fired),
                sandbox_url=sandbox_url,
            )

        if probes_fired >= budget and stop_reason != "budget":
            stop_reason = "budget"

        # Account OSS tokens. Diff against the pre-loop
        # snapshot — handles the case where the fuzzer
        # was reused across multiple scans.
        self.tokens_used.oss_in += self.fuzzer.usage.tokens_in - oss_in_before
        self.tokens_used.oss_out += self.fuzzer.usage.tokens_out - oss_out_before

        logger.info(
            "dual_model.iterate_done",
            probes_fired=probes_fired,
            observed=len(observed),
            stop_reason=stop_reason,
            oss_in=self.tokens_used.oss_in,
            oss_out=self.tokens_used.oss_out,
        )

        # Commercial summary → emit findings. The summary
        # is one LLM call at the end; its findings are
        # yielded to the caller.
        findings = await self._summarize_with_extractor(
            observed, route_map, sandbox_url, tokens
        )
        for f in findings:
            yield f
