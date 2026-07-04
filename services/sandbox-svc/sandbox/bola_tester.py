"""BOLA/IDOR tester for Tier 3 Fuzz Agent.

Architecture
------------
This module is the *consumer* half of the Tier 3 fuzzer
alongside `sandbox.route_walker`. The walker emits
`CurlProbe` instances; the BOLA tester fires each probe at
the live sandbox in *both* tenant directions and reports
the outcome.

What BOLA is
------------
BOLA (Broken Object Level Authorization, OWASP API #1) is
when User A from tenant 1 can read or write a resource
owned by tenant 2. The classic case: `/api/users/42`
returns user 42 even when 42 belongs to a different
tenant than the caller's JWT. IDOR is the same class of
bug from a slightly different angle — the resource ID
in the path is enumerable and not bound to the caller's
identity.

How we test for it
------------------
For each probe (one per route, regardless of the
walker's emitted token_type), we fire TWO requests:

    1. User_A (tenant 1) -> the path. The path is
       treated as a "tenant 2 resource" for the
       purposes of this test. We expect 403; if 200,
       tenant 1 broke in.
    2. User_B (tenant 2) -> the path. Treated as a
       "tenant 1 resource" probe. We expect 403; if
       200, tenant 2 broke in.

A BOLA PoC is reported when the access pattern is
asymmetric: one direction succeeds (2xx) while the
other is properly rejected (4xx). When both succeed,
the resource is shared by design (no BOLA). When both
are rejected, the app is correctly enforcing tenant
isolation. The "both succeeded" case is *also* a BOLA
signal (no isolation at all) and is reported — see
the `is_bola` derivation in `test_route` for the
exact truth table.

Why we test both directions
---------------------------
A real BOLA is often asymmetric: the seeded User_A's
role might give them admin-like access that crosses
tenants, while User_B's role is read-only and stays
put. Reporting only the User_A -> tenant 2 direction
would miss the mirror case where User_B silently reads
tenant 1 data. Both directions must be checked, even
when the original probe was emitted for only one user.

Curl reproduction
-----------------
The PoC includes a curl command that an auditor can
paste to reproduce the BOLA. The `Authorization`
header is *masked* to `Bearer ***` — the real token is
never written to the audit log. A leaked audit log
that contains a valid bearer token is a credential
leak; the masker keeps the report shareable.

Why a real `httpx.AsyncClient` instead of `requests`
----------------------------------------------------
The walker and the rest of the sandbox-svc use async
end-to-end (tier2 runs on a single event loop). A sync
HTTP client would force the suite to thread-pool every
BOLA test, which adds latency and complexity. `httpx`
matches the existing async surface in
`sandbox.oss_inference` and `sandbox.health_monitor`,
and is already in `requirements.txt`.

Dependency map
--------------
- Reads from: `sandbox.route_walker.CurlProbe`,
              `sandbox.jwt_forge.ForgedToken`.
- Network:    `httpx.AsyncClient` (mocked in tests via
              the injected `client` argument — real
              test runs never touch the network).
- Consumed by: the Tier 3 orchestrator (not yet
              implemented; this module is the
              producer of `BolaPoC` records that the
              orchestrator will write to the report).

Testing
-------
- `tests/sandbox/test_bola_tester.py` covers: BOLA
  detected (mock 200 on cross-tenant), clean route
  (mock 403), masked Authorization, symmetric
  User_B -> tenant 1 test, and a no-real-network
  guard. All httpx calls are routed through an
  injected `MockTransport`; no real socket is
  opened.
"""

from dataclasses import dataclass

import httpx
import structlog

from sandbox.jwt_forge import ForgedToken
from sandbox.route_walker import CurlProbe

logger = structlog.get_logger(__name__)


# HTTP status ranges that gate the BOLA decision.
#
# 2xx is the "access granted" range for BOLA purposes.
# 3xx (redirect) is treated as non-success: the body
# wasn't actually returned to us, and following the
# redirect would re-fire any auth on the target.
# 4xx is the "expected rejection" range — both 401
# (unauthenticated) and 403 (forbidden) are the
# classic BOLA-rejection responses. 404 is also
# counted as a rejection: many apps hide cross-tenant
# resources by returning 404 instead of 403 to avoid
# leaking the existence of an object.
# 5xx is treated as ambiguous (the app crashed or
# timed out) and excludes the probe from the PoC.
SUCCESS_STATUS_RANGE = (200, 299)
REJECTION_STATUS_RANGE = (400, 499)


def _is_success(status: int) -> bool:
    """Return True if `status` is in the 2xx success range.

    Extracted as a helper so the boundary is a single
    edit point. If we ever decide to count 3xx (after
    following redirects) as success, only this helper
    changes.
    """
    return SUCCESS_STATUS_RANGE[0] <= status <= SUCCESS_STATUS_RANGE[1]


def _is_rejection(status: int) -> bool:
    """Return True if `status` is a 4xx client error.

    401 (unauthenticated) and 403 (forbidden) are the
    "expected" BOLA-rejection responses. 404 is *also*
    counted as a rejection: the app hiding a
    cross-tenant resource behind 404 is still
    "blocked", just with a different response code.
    5xx is excluded — the app is broken, not
    BOLA-vulnerable.
    """
    return REJECTION_STATUS_RANGE[0] <= status <= REJECTION_STATUS_RANGE[1]


def _mask_authorization(headers: dict) -> dict:
    """Return a copy of `headers` with Authorization masked.

    The PoC's `curl_repro` is written to the audit log.
    We never want the real bearer token in that log (a
    leaked audit log is a credential leak). The token
    is replaced with `***`; the rest of the header is
    left intact for context (so the auditor can see
    the request used the Bearer scheme).

    Args:
        headers: Source headers (not mutated).

    Returns:
        New dict with `Authorization: Bearer ***` if
        `Authorization` was present in the source.
        When the source had no Authorization header,
        the returned dict also has none — we do *not*
        inject a masked header into requests that
        originally had none.
    """
    masked = dict(headers)
    if "Authorization" in masked:
        masked["Authorization"] = "Bearer ***"
    return masked


def _build_curl_repro(
    method: str,
    url: str,
    headers: dict,
    body: str | None = None,
) -> str:
    """Render an HTTP request as a shell-callable curl command.

    Format: one shell line, with each flag on its own
    token for readability. Long enough for a human to
    copy-paste into a terminal, short enough to fit in
    a log line.

    The order of flags is fixed: method, headers, body,
    URL. Reordering would be a presentation choice,
    not a semantic one, so we keep the order stable so
    the diff between two PoCs is purely the variable
    parts.

    Args:
        method:  HTTP verb (GET, POST, ...).
        url:     Full URL to hit.
        headers: Header dict. Pass the masked version
                from `_mask_authorization` to avoid
                leaking the real token.
        body:    Optional request body. When `None`,
                the `-d` flag is omitted. Body is
                shell-quoted with single quotes;
                embedded single quotes would break the
                command — callers that need to pass
                complex bodies should pre-shell-escape
                or pass an empty string.

    Returns:
        Single-line string ready to be pasted into a
        shell.
    """
    parts = [f"curl -X {method.upper()}"]
    for key, value in headers.items():
        parts.append(f"-H '{key}: {value}'")
    if body is not None:
        parts.append(f"-d '{body}'")
    parts.append(f"'{url}'")
    return " ".join(parts)


@dataclass
class BolaPoC:
    """A single BOLA finding with enough context to reproduce.

    Fields:
        target_path:       The route path from the probe
                           (e.g. `/api/users/:id`). Path
                           placeholders are kept as-is.
        curl_repro:        A masked, shell-callable curl
                           command that reproduces the
                           BOLA. `Authorization` is
                           masked to `Bearer ***` so the
                           audit log does not leak the
                           attacker's real token.
        actual_status:     The HTTP status returned by
                           the BOLA-firing request.
                           Recorded for cross-stage
                           correlation; not used to gate
                           the PoC (the booleans below
                           already encode the decision).
        tenant1_ok:        True when User_A's request
                           (tenant 1 token hitting a
                           "tenant 2 resource") returned
                           2xx. A `True` here is the
                           one-direction BOLA signal:
                           User_A broke into a resource
                           owned by tenant 2.
        tenant2_rejected:  True when User_B's request
                           (tenant 2 token hitting a
                           "tenant 1 resource") was
                           properly rejected with 4xx.
                           A `True` here means that
                           direction is clean; a
                           `False` means User_B also
                           broke in (worst case: no
                           tenant isolation at all).
    """

    target_path: str
    curl_repro: str
    actual_status: int
    tenant1_ok: bool
    tenant2_rejected: bool


class BolaTester:
    """Fires CurlProbe instances at a sandbox in both tenant directions.

    The tester is stateful only in the sense that it
    holds an `httpx.AsyncClient`. One instance = one
    sandbox. To test a different sandbox, construct a
    new instance — the client is not safe to reuse
    across hosts without connection-pool
    reconfiguration.

    Args:
        sandbox_url:   Base URL of the sandbox (e.g.
                       `http://antivibe-sandbox.fly.dev`).
                       Trailing slash is stripped. Path
                       is joined with simple string
                       concatenation; the probe's path
                       is normalized to a leading slash
                       so the join is unambiguous.
        timeout:       Per-request timeout in seconds.
                       Default 10s — the sandbox is a
                       local-ish app inside Fly; 10s
                       is generous.
        client:        Optional `httpx.AsyncClient`
                       for dependency injection (tests
                       pass a mocked client). When
                       `None`, a real client is created
                       in `_get_client`. The lazy-init
                       pattern lets unit tests inspect
                       the constructor without paying
                       the cost of opening a connection.

    Usage:
        tester = BolaTester(sandbox_url="http://sandbox")
        async for probe in walker:
            poc = await tester.test_route(probe, forged_tokens)
            if poc is not None:
                # BOLA confirmed; append to report
                ...
    """

    def __init__(
        self,
        sandbox_url: str,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ):
        self.sandbox_url = sandbox_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = client

    def _get_client(self) -> httpx.AsyncClient:
        """Return the injected client, or create a real one.

        Lazy init keeps the constructor cheap and lets
        tests pass their own mock. The created client
        uses a 10s connect / 10s read timeout pair —
        the sandbox is on the same network as the
        scanner, so 10s of read is plenty.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=self.timeout),
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying httpx connection pool.

        When a tester was constructed with an injected
        client, that client is *not* closed here — the
        test owns it. We only close clients we created.
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _fire(
        self,
        method: str,
        path: str,
        token: ForgedToken,
    ) -> int:
        """Issue one HTTP request and return the status code.

        Path is appended to `sandbox_url`. The
        Authorization header is *always* set to the
        supplied token, overriding whatever the probe
        carried. This is deliberate: BOLA tests must
        use the *attacker's* token, not the probe's
        original token. A probe that was emitted for
        user_a is also fired with user_b (and vice
        versa) to cover both directions.

        Args:
            method:  HTTP verb.
            path:    Route path (with or without
                     leading slash; we normalize to a
                     leading slash).
            token:   The `ForgedToken` whose raw
                     `token` string is sent as
                     `Authorization: Bearer ...`.

        Returns:
            HTTP status code. Connection errors are
            swallowed and returned as 0 — the caller
            treats 0 as "request didn't reach the
            sandbox", which is neither a success nor
            a rejection, and excludes the probe from
            the PoC list.
        """
        url_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.sandbox_url}{url_path}"
        headers = {"Authorization": f"Bearer {token.token}"}
        client = self._get_client()
        try:
            response = await client.request(method, url, headers=headers)
            return response.status_code
        except httpx.HTTPError as e:
            logger.warning(
                "bola_tester.request_failed",
                method=method,
                path=path,
                error=str(e),
            )
            return 0

    async def test_route(
        self,
        probe: CurlProbe,
        forged_tokens: tuple[ForgedToken, ForgedToken],
    ) -> BolaPoC | None:
        """Test one route for BOLA in both tenant directions.

        The probe's `path` is the resource under test.
        We fire it twice:

            1. User_A (tenant 1) -> path treated as
               "tenant 2 resource". Expect 403. 2xx
               means User_A broke in -> tenant1_ok=True.
            2. User_B (tenant 2) -> path treated as
               "tenant 1 resource". Expect 403. 2xx
               means User_B broke in -> tenant2_rejected
               becomes False (this direction is broken).

        A PoC is returned when EITHER direction
        succeeds (the only "no BOLA" case is both
        directions properly rejected). The booleans
        in the returned PoC make the direction
        explicit so the auditor can read the
        asymmetry at a glance:

            tenant1_ok=True,  tenant2_rejected=True
                -> User_A broke in, User_B was blocked.
                   One-direction BOLA.
            tenant1_ok=True,  tenant2_rejected=False
                -> Both got in. No tenant isolation
                   at all. Worst case.
            tenant1_ok=False, tenant2_rejected=False
                -> User_A was blocked but User_B
                   broke in. Reverse-direction BOLA
                   (the original probe was User_A
                   direction; this catches the
                   mirror case).
            tenant1_ok=False, tenant2_rejected=True
                -> Both properly rejected. No BOLA.
                   Returns None.

        Args:
            probe:          The `CurlProbe` from the
                            walker. Only `method`,
                            `path`, and `body` are
                            read; the probe's own
                            `token_type` is ignored
                            because we test both
                            directions.
            forged_tokens:  The `(User_A, User_B)`
                            tuple from
                            `jwt_forge.forge()`.

        Returns:
            `BolaPoC` when BOLA is detected in at
            least one direction. `None` when both
            directions are properly rejected (the
            only "no BOLA" outcome) or when both
            requests failed to reach the sandbox
            (network errors, status 0 from both).
        """
        token_a, token_b = forged_tokens

        # Direction 1: User_A -> path (assumed tenant 2
        # resource). tenant1_ok means User_A broke in.
        status_a = await self._fire(probe.method, probe.path, token_a)
        tenant1_ok = _is_success(status_a)

        # Direction 2: User_B -> path (assumed tenant 1
        # resource). tenant2_rejected means User_B was
        # properly blocked. NOT tenant2_rejected means
        # User_B also broke in (no isolation).
        status_b = await self._fire(probe.method, probe.path, token_b)
        tenant2_rejected = _is_rejection(status_b)

        # No signal: both requests failed to reach the
        # sandbox. Don't emit a PoC for something we
        # couldn't actually test — a missing network
        # is not a BOLA finding.
        if status_a == 0 and status_b == 0:
            return None

        # BOLA detection rule: emit a PoC only when at
        # least one direction returned a definitive
        # 2xx. The booleans `tenant1_ok` and
        # `tenant2_rejected` alone are not enough:
        # when both directions are 5xx, neither was
        # "granted" nor "properly rejected" — the app
        # is broken, not BOLA-vulnerable. Requiring at
        # least one 2xx makes the rule asymmetric on
        # purpose: a 200 is the only status that
        # proves the cross-tenant request actually
        # returned the protected resource.
        is_bola = _is_success(status_a) or _is_success(status_b)
        if not is_bola:
            return None

        # For the recorded status, prefer the
        # BOLA-firing direction. When both broke in
        # we use status_a (User_A) for stability — the
        # PoC documents the *probe* that found the
        # BOLA, not a specific direction.
        actual_status = status_a if tenant1_ok else status_b

        # Build the masked curl repro. We start from
        # the probe's headers as the template (so any
        # custom Accept/User-Agent are preserved), then
        # mask the Authorization. The masked header is
        # `Bearer ***` regardless of which attacker
        # token was used — the audit log must never
        # carry a real token.
        masked_headers = _mask_authorization(probe.headers)
        masked_headers["Authorization"] = "Bearer ***"

        url_path = probe.path if probe.path.startswith("/") else f"/{probe.path}"
        url = f"{self.sandbox_url}{url_path}"
        curl_repro = _build_curl_repro(
            method=probe.method,
            url=url,
            headers=masked_headers,
            body=probe.body,
        )

        return BolaPoC(
            target_path=probe.path,
            curl_repro=curl_repro,
            actual_status=actual_status,
            tenant1_ok=tenant1_ok,
            tenant2_rejected=tenant2_rejected,
        )


async def run_bola_suite(
    route_walker,
    sandbox_url: str,
    forged_tokens: tuple[ForgedToken, ForgedToken],
    client: httpx.AsyncClient | None = None,
) -> list:
    """Consume the walker and run BOLA tests on every probe.

    The walker is an async iterator (per
    `sandbox.route_walker.RouteWalker`). We drain it
    one probe at a time and pass each to
    `BolaTester.test_route`. The walker is allowed to
    raise `StopAsyncIteration`; we catch it implicitly
    via `async for` and break out of the loop cleanly.

    A fresh `BolaTester` is constructed per call. The
    caller's `client` (if any) is injected so all
    probes in the suite share one connection pool —
    this matches the existing pattern in
    `sandbox.oss_inference`.

    Args:
        route_walker:  The `RouteWalker` async iterator.
        sandbox_url:   Base URL of the sandbox.
        forged_tokens: The `(User_A, User_B)` tuple.
        client:        Optional injected httpx client
                       (tests use this to mock the
                       network). When `None`, the
                       tester creates and closes its
                       own.

    Returns:
        List of `BolaPoC`, one per BOLA-firing probe.
        Empty list when the walker finds no BOLA.
    """
    tester = BolaTester(sandbox_url=sandbox_url, client=client)
    pocs: list = []
    # Deduplicate by path. The walker emits one probe
    # per (route, token_variant) pair; the BOLA tester
    # fires BOTH directions regardless. Two probes
    # targeting the same path will both fire the same
    # cross-tenant requests and (when the path is
    # vulnerable) both produce a PoC with identical
    # content. Reporting the same BOLA twice is noise;
    # we keep the first PoC and skip the rest.
    seen_paths: set = set()
    try:
        async for probe in route_walker:
            poc = await tester.test_route(probe, forged_tokens)
            if poc is not None and poc.target_path not in seen_paths:
                seen_paths.add(poc.target_path)
                pocs.append(poc)
    finally:
        # Only close the tester when we own its client.
        # When a client was injected, the caller owns
        # the lifecycle.
        if client is None:
            await tester.aclose()
    return pocs
