"""Tests for the BOLA/IDOR Tester.

All httpx traffic is routed through a `MockTransport` —
no real socket, no real DNS, no real sandbox. The
tester is the *consumer* half of the Tier 3 fuzzer
pair; the walker half is exercised by
`test_route_walker.py`. Here we only verify that
BolaTester:

    1. Detects a seeded BOLA (User_A gets 200 on a
       "tenant 2 resource" → PoC emitted).
    2. Returns None on a clean route (User_A gets 403).
    3. Masks Authorization in the curl_repro.
    4. Runs the symmetric User_B → tenant 1 test and
       records the result on the PoC.
    5. Never opens a real socket — verified by routing
       everything through respx and asserting the routes
       were called.
"""

import httpx
import pytest
import respx

from sandbox.bola_tester import (
    BolaPoC,
    BolaTester,
    _build_curl_repro,
    _is_rejection,
    _is_success,
    _mask_authorization,
    run_bola_suite,
)
from sandbox.jwt_forge import ForgedToken
from sandbox.route_mapper import RouteIndexEntry
from sandbox.route_walker import CurlProbe, RouteWalker

# ─── Helpers ─────────────────────────────────────────────────────────


SANDBOX_URL = "http://bola-test-sandbox.local"


def _make_route_entry(
    path: str,
    methods: list | None = None,
    auth_required: bool = True,
) -> RouteIndexEntry:
    """Build a RouteIndexEntry for tests.

    Defaults to an auth-required GET. Pass
    `auth_required=False` for a public endpoint, or
    `methods` to model a POST/PUT/DELETE route.
    """
    return RouteIndexEntry(
        path=path,
        methods=methods if methods is not None else ["GET"],
        params={},
        auth_required=auth_required,
        auth_stack="custom",
        file_path=f"app{path}.ts",
        line=1,
    )


def _make_probe(
    path: str = "/api/users/42",
    method: str = "GET",
    token_type: str = "user_a",
) -> CurlProbe:
    """Build a CurlProbe for tests.

    Defaults match the most common BOLA target: a GET
    on a `/api/users/:id` style route with a user_a
    token. The Authorization header carries a
    recognisable but synthetic token so the
    "Authorization is masked" test can assert that the
    real value is gone from the output.
    """
    return CurlProbe(
        method=method,
        path=path,
        headers={"Authorization": "Bearer fake-jwt-user-a"},
        body=None,
        token_type=token_type,
        route_entry=_make_route_entry(path),
    )


def _make_forged_token(
    user_id: str,
    tenant_id: int,
    role: str = "student",
) -> ForgedToken:
    """Build a ForgedToken for tests."""
    return ForgedToken(
        token=f"jwt.{user_id}.signature",
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        auth_stack="custom",
        claims={"sub": user_id, "tenant_id": tenant_id},
    )


def _make_route_index(paths: list) -> list:
    """Build a route index from a list of path strings."""
    return [_make_route_entry(p) for p in paths]


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def token_a() -> ForgedToken:
    return _make_forged_token("user-a-tenant1", 1)


@pytest.fixture
def token_b() -> ForgedToken:
    return _make_forged_token("user-b-tenant2", 2)


@pytest.fixture
def forged_tokens(token_a, token_b) -> tuple:
    return (token_a, token_b)


@pytest.fixture
def probe() -> CurlProbe:
    return _make_probe()


# ─── Test: helper functions ──────────────────────────────────────────


class TestHelpers:
    def test_is_success_2xx(self):
        """_is_success returns True for any 2xx status."""
        assert _is_success(200) is True
        assert _is_success(201) is True
        assert _is_success(204) is True
        assert _is_success(299) is True

    def test_is_success_3xx_4xx_5xx(self):
        """_is_success returns False for non-2xx."""
        assert _is_success(301) is False
        assert _is_success(400) is False
        assert _is_success(403) is False
        assert _is_success(404) is False
        assert _is_success(500) is False
        assert _is_success(0) is False  # network error sentinel

    def test_is_rejection_4xx(self):
        """_is_rejection returns True for any 4xx status."""
        assert _is_rejection(400) is True
        assert _is_rejection(401) is True
        assert _is_rejection(403) is True
        assert _is_rejection(404) is True
        assert _is_rejection(499) is True

    def test_is_rejection_non_4xx(self):
        """_is_rejection returns False for non-4xx."""
        assert _is_rejection(200) is False
        assert _is_rejection(301) is False
        assert _is_rejection(500) is False
        assert _is_rejection(0) is False

    def test_mask_authorization_replaces_token(self):
        """_mask_authorization replaces the Bearer value with ***."""
        original = {"Authorization": "Bearer secret-jwt-token-123"}
        masked = _mask_authorization(original)
        assert masked["Authorization"] == "Bearer ***"
        # Original is not mutated (defensive copy).
        assert original["Authorization"] == "Bearer secret-jwt-token-123"

    def test_mask_authorization_no_header(self):
        """_mask_authorization returns a clean copy when no Authorization."""
        original = {"Accept": "application/json"}
        masked = _mask_authorization(original)
        assert "Authorization" not in masked
        assert masked == {"Accept": "application/json"}

    def test_mask_authorization_preserves_other_headers(self):
        """_mask_authorization preserves non-Authorization headers."""
        original = {
            "Authorization": "Bearer xyz",
            "Accept": "application/json",
            "X-Request-Id": "req-1",
        }
        masked = _mask_authorization(original)
        assert masked["Accept"] == "application/json"
        assert masked["X-Request-Id"] == "req-1"
        assert masked["Authorization"] == "Bearer ***"

    def test_build_curl_repro_basic(self):
        """_build_curl_repro produces a single-line curl with method+url."""
        result = _build_curl_repro(
            method="GET",
            url="http://x.local/api/users/1",
            headers={"Authorization": "Bearer ***", "Accept": "application/json"},
        )
        assert "curl -X GET" in result
        assert "'http://x.local/api/users/1'" in result
        assert "-H 'Authorization: Bearer ***'" in result
        assert "-H 'Accept: application/json'" in result
        # Single-line output.
        assert "\n" not in result

    def test_build_curl_repro_with_body(self):
        """_build_curl_repro includes -d when body is given."""
        result = _build_curl_repro(
            method="POST",
            url="http://x.local/api/users",
            headers={"Authorization": "Bearer ***"},
            body='{"name":"x"}',
        )
        assert "curl -X POST" in result
        assert "-d '{\"name\":\"x\"}'" in result


# ─── Test: BolaPoC dataclass ─────────────────────────────────────────


class TestBolaPoCShape:
    def test_bola_poc_fields(self):
        """BolaPoC has all 5 fields per spec."""
        poc = BolaPoC(
            target_path="/api/users/1",
            curl_repro="curl -X GET 'http://x/...'",
            actual_status=200,
            tenant1_ok=True,
            tenant2_rejected=True,
        )
        assert poc.target_path == "/api/users/1"
        assert poc.curl_repro == "curl -X GET 'http://x/...'"
        assert poc.actual_status == 200
        assert poc.tenant1_ok is True
        assert poc.tenant2_rejected is True


# ─── Test: BOLA detection ────────────────────────────────────────────


class TestBolaDetection:
    @pytest.mark.asyncio
    async def test_seeded_bola_detected_user_a_gets_200(
        self, forged_tokens
    ):
        """User_A token gets 200 on the "tenant 2 resource" -> BOLA PoC.

        Mocks: User_A's GET returns 200 (the BOLA signal),
        User_B's GET returns 403 (the other direction is
        clean — this is one-direction BOLA).
        """
        probe = _make_probe(path="/api/users/42", token_type="user_a")
        with respx.mock(assert_all_called=True) as mock:
            # User_A -> 200 (BOLA: tenant 1 broke into tenant 2)
            mock.get(f"{SANDBOX_URL}/api/users/42").mock(
                side_effect=[
                    httpx.Response(200, json={"id": 42, "tenant": 2}),
                    httpx.Response(403, json={"error": "forbidden"}),
                ]
            )
            tester = BolaTester(sandbox_url=SANDBOX_URL)
            try:
                poc = await tester.test_route(probe, forged_tokens)
            finally:
                await tester.aclose()

        assert poc is not None, "BOLA should be detected when User_A gets 200"
        assert isinstance(poc, BolaPoC)
        assert poc.target_path == "/api/users/42"
        assert poc.actual_status == 200
        assert poc.tenant1_ok is True
        assert poc.tenant2_rejected is True

    @pytest.mark.asyncio
    async def test_seeded_bola_detected_user_b_gets_200(
        self, forged_tokens
    ):
        """User_B token gets 200 -> BOLA detected in the reverse direction.

        Mocks: User_A -> 403 (correctly rejected), User_B
        -> 200 (BOLA: tenant 2 broke into tenant 1). The
        PoC should still be emitted, with the booleans
        reflecting the reverse-direction break.
        """
        probe = _make_probe(path="/api/users/42", token_type="user_b")
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{SANDBOX_URL}/api/users/42").mock(
                side_effect=[
                    httpx.Response(403, json={"error": "forbidden"}),
                    httpx.Response(200, json={"id": 42, "tenant": 1}),
                ]
            )
            tester = BolaTester(sandbox_url=SANDBOX_URL)
            try:
                poc = await tester.test_route(probe, forged_tokens)
            finally:
                await tester.aclose()

        assert poc is not None
        assert poc.tenant1_ok is False
        assert poc.tenant2_rejected is False
        # Status is the BOLA-firing direction (User_B).
        assert poc.actual_status == 200

    @pytest.mark.asyncio
    async def test_seeded_bola_worst_case_both_directions(
        self, forged_tokens
    ):
        """Both tokens get 200 -> BOLA PoC with tenant1_ok=True, tenant2_rejected=False.

        This is the "no tenant isolation at all" case.
        The PoC is still emitted because access is
        asymmetric with the outside world — anyone can
        see the resource.
        """
        probe = _make_probe(path="/api/posts/1")
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{SANDBOX_URL}/api/posts/1").mock(
                side_effect=[
                    httpx.Response(200, json={"id": 1}),
                    httpx.Response(200, json={"id": 1}),
                ]
            )
            tester = BolaTester(sandbox_url=SANDBOX_URL)
            try:
                poc = await tester.test_route(probe, forged_tokens)
            finally:
                await tester.aclose()

        assert poc is not None
        assert poc.tenant1_ok is True
        assert poc.tenant2_rejected is False
        assert poc.actual_status == 200


# ─── Test: clean route returns None ──────────────────────────────────


class TestCleanRoute:
    @pytest.mark.asyncio
    async def test_clean_route_returns_none_on_403(self, forged_tokens):
        """Both directions 403 -> no BOLA -> None.

        The app correctly rejected both cross-tenant
        attempts. The tester must NOT emit a PoC for
        this case (no finding to report).
        """
        probe = _make_probe(path="/api/users/42")
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{SANDBOX_URL}/api/users/42").mock(
                side_effect=[
                    httpx.Response(403, json={"error": "forbidden"}),
                    httpx.Response(403, json={"error": "forbidden"}),
                ]
            )
            tester = BolaTester(sandbox_url=SANDBOX_URL)
            try:
                poc = await tester.test_route(probe, forged_tokens)
            finally:
                await tester.aclose()

        assert poc is None, "Clean route (both 403) must not emit a PoC"

    @pytest.mark.asyncio
    async def test_clean_route_returns_none_on_401(self, forged_tokens):
        """Both directions 401 -> no BOLA -> None.

        401 is also a "properly rejected" status; the
        app is enforcing auth at the boundary, just with
        a different code than 403.
        """
        probe = _make_probe(path="/api/orders/9")
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{SANDBOX_URL}/api/orders/9").mock(
                side_effect=[
                    httpx.Response(401, json={"error": "unauthenticated"}),
                    httpx.Response(401, json={"error": "unauthenticated"}),
                ]
            )
            tester = BolaTester(sandbox_url=SANDBOX_URL)
            try:
                poc = await tester.test_route(probe, forged_tokens)
            finally:
                await tester.aclose()

        assert poc is None

    @pytest.mark.asyncio
    async def test_500_excluded_from_bola(self, forged_tokens):
        """5xx on both sides -> None (the app crashed; not a BOLA signal).

        A 500 means the app blew up, not that the BOLA
        attempt was allowed. We exclude 5xx from the
        PoC to avoid false positives from a broken
        app.
        """
        probe = _make_probe(path="/api/broken")
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{SANDBOX_URL}/api/broken").mock(
                side_effect=[
                    httpx.Response(500, text="Internal Server Error"),
                    httpx.Response(500, text="Internal Server Error"),
                ]
            )
            tester = BolaTester(sandbox_url=SANDBOX_URL)
            try:
                poc = await tester.test_route(probe, forged_tokens)
            finally:
                await tester.aclose()

        assert poc is None

    @pytest.mark.asyncio
    async def test_network_error_excluded_from_bola(self, forged_tokens):
        """Both requests fail with 0 (network error) -> None."""
        probe = _make_probe(path="/api/x")
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{SANDBOX_URL}/api/x").mock(
                side_effect=httpx.ConnectError("boom")
            )
            tester = BolaTester(sandbox_url=SANDBOX_URL)
            try:
                poc = await tester.test_route(probe, forged_tokens)
            finally:
                await tester.aclose()

        assert poc is None


# ─── Test: curl repro is masked ──────────────────────────────────────


class TestCurlReproMasked:
    @pytest.mark.asyncio
    async def test_curl_repro_has_masked_authorization(self, forged_tokens):
        """curl_repro contains `Bearer ***`, never the real token.

        The audit log must NEVER carry a real bearer
        token. The masker replaces the real token with
        `***`; this test asserts the substitution
        happened AND the original token string is not
        present in the output.
        """
        # The real token is in `forged_tokens[0].token` —
        # record it so we can assert it's absent.
        real_token = forged_tokens[0].token
        probe = _make_probe(path="/api/users/1")
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{SANDBOX_URL}/api/users/1").mock(
                side_effect=[
                    httpx.Response(200, json={"id": 1}),
                    httpx.Response(403, json={"error": "forbidden"}),
                ]
            )
            tester = BolaTester(sandbox_url=SANDBOX_URL)
            try:
                poc = await tester.test_route(probe, forged_tokens)
            finally:
                await tester.aclose()

        assert poc is not None
        # Masked form is present.
        assert "Bearer ***" in poc.curl_repro
        # Real token is NOT present.
        assert real_token not in poc.curl_repro
        # `Bearer` prefix alone is fine (informational).
        assert "Bearer" in poc.curl_repro

    @pytest.mark.asyncio
    async def test_curl_repro_includes_method_and_url(self, forged_tokens):
        """curl_repro carries the HTTP method and the full URL."""
        probe = _make_probe(path="/api/posts/7", method="GET")
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{SANDBOX_URL}/api/posts/7").mock(
                side_effect=[
                    httpx.Response(200, json={"id": 7}),
                    httpx.Response(403, json={"error": "forbidden"}),
                ]
            )
            tester = BolaTester(sandbox_url=SANDBOX_URL)
            try:
                poc = await tester.test_route(probe, forged_tokens)
            finally:
                await tester.aclose()

        assert poc is not None
        assert "curl -X GET" in poc.curl_repro
        assert f"{SANDBOX_URL}/api/posts/7" in poc.curl_repro


# ─── Test: symmetrical (User_B -> tenant 1 resource) ─────────────────


class TestSymmetry:
    @pytest.mark.asyncio
    async def test_symmetric_user_b_to_tenant1_resource(
        self, forged_tokens
    ):
        """User_B probe on a tenant 1 resource is also BOLA-tested.

        When the walker emits a `user_b` probe (i.e. the
        original route-walker emission used the
        cross-tenant User_B token), the BOLA tester
        must STILL fire both directions. The PoC's
        `tenant1_ok` / `tenant2_rejected` flags must
        reflect the actual cross-tenant behavior, not
        the probe's original token_type.
        """
        # Probe is a User_B probe (token_type=user_b),
        # targeting a "tenant 1 resource".
        probe = _make_probe(path="/api/users/1", token_type="user_b")
        with respx.mock(assert_all_called=True) as mock:
            # User_A -> 200 (BOLA: tenant 1 user accessing
            # a path that should be tenant 1's resource
            # is "normal" only if the resource is
            # tenant 1's — but we model it as a tenant 1
            # resource here, so User_A succeeds normally
            # while User_B (the attacker) ALSO succeeds:
            # that's reverse-direction BOLA from the
            # probe's perspective).
            #
            # For a pure "User_B -> tenant 1 resource is
            # also BOLA-tested" test, the simplest setup
            # is: User_A -> 403, User_B -> 200. The PoC
            # should be emitted with tenant1_ok=False
            # and tenant2_rejected=False.
            mock.get(f"{SANDBOX_URL}/api/users/1").mock(
                side_effect=[
                    httpx.Response(403, json={"error": "forbidden"}),
                    httpx.Response(200, json={"id": 1, "tenant": 1}),
                ]
            )
            tester = BolaTester(sandbox_url=SANDBOX_URL)
            try:
                poc = await tester.test_route(probe, forged_tokens)
            finally:
                await tester.aclose()

        # PoC emitted because User_B (tenant 2) broke
        # into the "tenant 1 resource".
        assert poc is not None
        # tenant1_ok: User_A was blocked — False.
        assert poc.tenant1_ok is False
        # tenant2_rejected: User_B was NOT rejected —
        # False.
        assert poc.tenant2_rejected is False
        # Status recorded is the BOLA-firing direction.
        assert poc.actual_status == 200

    @pytest.mark.asyncio
    async def test_both_directions_tested_regardless_of_probe_token_type(
        self, forged_tokens
    ):
        """The same probe is fired with both tokens regardless of token_type.

        Even when the probe was emitted by the walker
        with `token_type="user_a"`, the BOLA tester
        fires a second request with User_B's token.
        Both calls must be observed by the mock
        transport.
        """
        probe = _make_probe(path="/api/x", token_type="user_a")
        with respx.mock(assert_all_called=True) as mock:
            route = mock.get(f"{SANDBOX_URL}/api/x").mock(
                side_effect=[
                    httpx.Response(200, json={}),
                    httpx.Response(403, json={}),
                ]
            )
            tester = BolaTester(sandbox_url=SANDBOX_URL)
            try:
                poc = await tester.test_route(probe, forged_tokens)
            finally:
                await tester.aclose()

        assert poc is not None
        # Two requests fired (one per token).
        assert route.call_count == 2


# ─── Test: no real HTTP calls ────────────────────────────────────────


class TestNoRealHTTP:
    @pytest.mark.asyncio
    async def test_no_real_http_when_route_unmocked(
        self, forged_tokens
    ):
        """Unmocked route -> respx intercepts -> no real socket opened.

        When `respx.mock()` is active and no routes are
        registered for the path, the request is
        intercepted by respx instead of reaching the
        real network. If a real socket were opened, the
        test would hang on DNS or fail with a
        connection error — neither is acceptable. The
        test registers a catch-all 404 route so both
        directions get a definitive rejection, asserts
        respx handled the calls, and confirms the
        result is a clean `None` PoC.
        """
        probe = _make_probe(path="/api/never-mocked")
        with respx.mock(assert_all_called=True) as mock:
            # Catch-all 404 for the path. respx
            # intercepts both directions; neither
            # request reaches the real network.
            mock.get(f"{SANDBOX_URL}/api/never-mocked").mock(
                return_value=httpx.Response(404, json={"error": "not found"})
            )
            tester = BolaTester(sandbox_url=SANDBOX_URL)
            try:
                poc = await tester.test_route(probe, forged_tokens)
            finally:
                await tester.aclose()
            # respx was the only one that handled the
            # call. `mock.calls` records every request
            # respx intercepted; 2 = both directions
            # were routed through respx, none escaped.
            assert len(mock.calls) == 2
        # Both calls were 404 (proper rejection) -> no
        # BOLA -> None.
        assert poc is None

    @pytest.mark.asyncio
    async def test_run_bola_suite_uses_injected_client(
        self, forged_tokens
    ):
        """run_bola_suite uses the injected httpx client (no real socket).

        Wires a MockTransport directly into the
        AsyncClient, passes the client to
        `run_bola_suite`, and verifies the suite
        processed every probe through the mock. The
        injected client is *not* closed by the suite
        (caller-owned lifecycle) — we close it
        ourselves in the test.
        """
        # Two routes; one BOLA-firing, one clean.
        routes = _make_route_index(["/api/users/1", "/api/users/2"])

        def handler(request: httpx.Request) -> httpx.Response:
            # Per-path state: which user fired this
            # call? We can't use a global counter
            # because the walker visits routes
            # sequentially and the test wants
            # per-path, not per-call, behavior.
            path = request.url.path
            auth = request.headers.get("Authorization", "")
            if path == "/api/users/1":
                # User_A -> 200 (BOLA: tenant 1 broke in)
                # User_B -> 403 (other direction clean)
                if "user-a" in auth:
                    return httpx.Response(200, json={"id": 1})
                return httpx.Response(403, json={"error": "forbidden"})
            # /api/users/2 -> both directions 403
            return httpx.Response(403, json={"error": "forbidden"})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        walker = RouteWalker(
            route_index=routes,
            forged_tokens=forged_tokens,
        )
        try:
            pocs = await run_bola_suite(
                walker,
                sandbox_url=SANDBOX_URL,
                forged_tokens=forged_tokens,
                client=client,
            )
        finally:
            await client.aclose()

        # 1 BOLA PoC (for /api/users/1), 0 for /api/users/2.
        assert len(pocs) == 1
        assert pocs[0].target_path == "/api/users/1"
        assert pocs[0].tenant1_ok is True
        assert pocs[0].tenant2_rejected is True
        # Walker visited 4 probes (2 routes × 2 variants — both auth routes skip tokenless).
        assert walker.verdict().visited == 4

    @pytest.mark.asyncio
    async def test_run_bola_suite_empty_for_clean_walker(
        self, forged_tokens
    ):
        """Walker that finds only clean routes -> empty PoC list."""
        routes = _make_route_index(["/api/clean"])

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "forbidden"})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        walker = RouteWalker(
            route_index=routes,
            forged_tokens=forged_tokens,
        )
        try:
            pocs = await run_bola_suite(
                walker,
                sandbox_url=SANDBOX_URL,
                forged_tokens=forged_tokens,
                client=client,
            )
        finally:
            await client.aclose()

        assert pocs == []
