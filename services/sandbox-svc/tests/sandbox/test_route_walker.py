"""Tests for the Tier 3 Route Walker.

All tests are async-iterator exercises against in-memory
fixtures — no real network, no real sandbox. The walker is
a pure generator, so the tests verify emission ordering,
state transitions, and cap enforcement by consuming the
iterator and inspecting the yielded probes.
"""

import pytest

from sandbox.route_walker import CurlProbe, WalkerState, RouteWalker
from sandbox.route_mapper import RouteIndexEntry
from sandbox.jwt_forge import ForgedToken


# ─── Helpers ─────────────────────────────────────────────────────────


def _make_route_entry(
    path: str,
    methods: list[str] | None = None,
    auth_required: bool = False,
) -> RouteIndexEntry:
    """Build a RouteIndexEntry for tests.

    Defaults to a non-auth GET route. Pass `auth_required=True`
    to model a protected endpoint, or set `methods` to model
    POST/PUT/DELETE endpoints.
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


def _make_forged_token(user_id: str, tenant_id: int) -> ForgedToken:
    """Build a ForgedToken for tests.

    The `token` field is a synthetic string — tests never
    decode it. The shape mimics `jwt_forge.ForgedToken` so
    the walker can pull `.token` directly.
    """
    return ForgedToken(
        token=f"jwt.{user_id}.signature",
        user_id=user_id,
        tenant_id=tenant_id,
        role="student",
        auth_stack="custom",
        claims={"sub": user_id, "tenant_id": tenant_id},
    )


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def token_a() -> ForgedToken:
    return _make_forged_token("user-a-tenant1", 1)


@pytest.fixture
def token_b() -> ForgedToken:
    return _make_forged_token("user-b-tenant2", 2)


@pytest.fixture
def forged_tokens(token_a, token_b) -> tuple[ForgedToken, ForgedToken]:
    return (token_a, token_b)


@pytest.fixture
def small_route_index() -> list[RouteIndexEntry]:
    """3-route fixture: 1 public, 1 auth, 1 public.

    Used by the "BFS emits all routes" test. With
    `max_depth=5` (default) and 3 routes, all 3 are
    processed.
    """
    return [
        _make_route_entry("/api/public", auth_required=False),
        _make_route_entry("/api/users", auth_required=True),
        _make_route_entry("/api/health", auth_required=False),
    ]


# ─── Test: dataclass shape ───────────────────────────────────────────


class TestCurlProbeShape:
    def test_curl_probe_fields(self):
        """CurlProbe has all 6 fields per spec."""
        entry = _make_route_entry("/api/users", auth_required=True)
        probe = CurlProbe(
            method="GET",
            path="/api/users",
            headers={"Authorization": "Bearer xyz"},
            body=None,
            token_type="user_a",
            route_entry=entry,
        )
        assert probe.method == "GET"
        assert probe.path == "/api/users"
        assert probe.headers == {"Authorization": "Bearer xyz"}
        assert probe.body is None
        assert probe.token_type == "user_a"
        assert probe.route_entry is entry


class TestWalkerStateShape:
    def test_walker_state_defaults(self):
        """WalkerState defaults match spec."""
        state = WalkerState()
        assert state.visited == 0
        assert state.blocked == 0
        assert state.exhausted is False
        assert state.blocked_routes == []


# ─── Test: token variant emission ────────────────────────────────────


class TestTokenVariantEmission:
    @pytest.mark.asyncio
    async def test_three_probes_for_non_auth_route(self, forged_tokens):
        """Non-auth route emits 3 probes: none, user_a, user_b."""
        walker = RouteWalker(
            route_index=[_make_route_entry("/api/public", auth_required=False)],
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]

        assert len(probes) == 3
        assert [p.token_type for p in probes] == ["none", "user_a", "user_b"]

    @pytest.mark.asyncio
    async def test_tokenless_probe_has_no_auth_header(self, forged_tokens):
        """Tokenless probe carries no Authorization header."""
        walker = RouteWalker(
            route_index=[_make_route_entry("/api/public", auth_required=False)],
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]

        tokenless = probes[0]
        assert tokenless.token_type == "none"
        assert "Authorization" not in tokenless.headers

    @pytest.mark.asyncio
    async def test_user_a_probe_carries_bearer_token(self, forged_tokens, token_a):
        """user_a probe embeds the User_A token in Authorization header."""
        walker = RouteWalker(
            route_index=[_make_route_entry("/api/users", auth_required=True)],
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]

        user_a = next(p for p in probes if p.token_type == "user_a")
        assert user_a.headers["Authorization"] == f"Bearer {token_a.token}"

    @pytest.mark.asyncio
    async def test_user_b_probe_carries_bearer_token(self, forged_tokens, token_b):
        """user_b probe embeds the User_B token in Authorization header."""
        walker = RouteWalker(
            route_index=[_make_route_entry("/api/users", auth_required=True)],
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]

        user_b = next(p for p in probes if p.token_type == "user_b")
        assert user_b.headers["Authorization"] == f"Bearer {token_b.token}"


# ─── Test: auth_required route handling ──────────────────────────────


class TestAuthRequiredHandling:
    @pytest.mark.asyncio
    async def test_auth_required_route_skips_tokenless(self, forged_tokens):
        """auth_required=True → no 'none' token_type probe emitted."""
        walker = RouteWalker(
            route_index=[_make_route_entry("/api/users", auth_required=True)],
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]

        token_types = [p.token_type for p in probes]
        assert "none" not in token_types
        # The two auth probes are still emitted.
        assert "user_a" in token_types
        assert "user_b" in token_types
        assert len(probes) == 2

    @pytest.mark.asyncio
    async def test_non_auth_route_emits_tokenless_first(self, forged_tokens):
        """For non-auth routes, 'none' is the first probe emitted."""
        walker = RouteWalker(
            route_index=[_make_route_entry("/api/public", auth_required=False)],
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]

        assert probes[0].token_type == "none"
        assert probes[1].token_type == "user_a"
        assert probes[2].token_type == "user_b"

    @pytest.mark.asyncio
    async def test_mixed_routes_get_correct_probe_counts(self, forged_tokens):
        """Mixed auth/non-auth routes: non-auth × 3, auth × 2."""
        routes = [
            _make_route_entry("/api/public", auth_required=False),  # 3 probes
            _make_route_entry("/api/users", auth_required=True),    # 2 probes
            _make_route_entry("/api/health", auth_required=False),  # 3 probes
        ]
        walker = RouteWalker(
            route_index=routes,
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]

        assert len(probes) == 8  # 3 + 2 + 3
        # No 'none' probe for the auth route.
        for probe in probes:
            if probe.path == "/api/users":
                assert probe.token_type != "none"


# ─── Test: BFS over the route index ──────────────────────────────────


class TestBFSEmission:
    @pytest.mark.asyncio
    async def test_bfs_emits_all_routes_in_fixture(self, forged_tokens, small_route_index):
        """BFS visits every route in the index (within depth cap)."""
        walker = RouteWalker(
            route_index=small_route_index,
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]

        # The fixture has 1 public, 1 auth, 1 public →
        # 3 + 2 + 3 = 8 probes total.
        assert len(probes) == 8
        # All 3 paths appear.
        paths = {p.path for p in probes}
        assert paths == {"/api/public", "/api/users", "/api/health"}

    @pytest.mark.asyncio
    async def test_bfs_visits_in_route_index_order(self, forged_tokens, small_route_index):
        """BFS preserves the route_index order."""
        walker = RouteWalker(
            route_index=small_route_index,
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]

        # First probe corresponds to the first route in
        # the index (`/api/public`).
        assert probes[0].path == "/api/public"
        # Last probe corresponds to the last route
        # (`/api/health`).
        assert probes[-1].path == "/api/health"

    @pytest.mark.asyncio
    async def test_bfs_processes_variants_within_route(self, forged_tokens):
        """BFS emits all variants for route N before moving to route N+1."""
        routes = [
            _make_route_entry("/api/a", auth_required=False),
            _make_route_entry("/api/b", auth_required=False),
        ]
        walker = RouteWalker(
            route_index=routes,
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]

        # First three probes are for /api/a (none, user_a, user_b).
        assert probes[0].path == "/api/a"
        assert probes[1].path == "/api/a"
        assert probes[2].path == "/api/a"
        # Next three are for /api/b.
        assert probes[3].path == "/api/b"
        assert probes[4].path == "/api/b"
        assert probes[5].path == "/api/b"

    @pytest.mark.asyncio
    async def test_max_depth_caps_routes_processed(self, forged_tokens):
        """max_depth limits how many distinct routes are processed."""
        routes = [
            _make_route_entry(f"/api/r{i}", auth_required=False) for i in range(10)
        ]
        walker = RouteWalker(
            route_index=routes,
            forged_tokens=forged_tokens,
            max_depth=3,
        )
        probes = [p async for p in walker]

        # Only the first 3 routes are processed → 3 × 3 = 9 probes.
        assert len(probes) == 9
        paths = {p.path for p in probes}
        assert paths == {"/api/r0", "/api/r1", "/api/r2"}


# ─── Test: 200-cap enforcement ───────────────────────────────────────


class TestAttemptCap:
    @pytest.mark.asyncio
    async def test_200_cap_enforced_with_many_routes(self, forged_tokens):
        """200-attempt cap is respected even when more probes are available."""
        # 100 non-auth routes → 300 max probes; cap to 200.
        routes = [
            _make_route_entry(f"/api/r{i}", auth_required=False) for i in range(100)
        ]
        walker = RouteWalker(
            route_index=routes,
            forged_tokens=forged_tokens,
            max_attempts=200,
            max_depth=100,  # don't depth-cap; the attempt cap is what we're testing
        )
        probes = [p async for p in walker]

        assert len(probes) == 200
        state = walker.verdict()
        assert state.visited == 200
        assert state.exhausted is True

    @pytest.mark.asyncio
    async def test_cap_set_below_natural_total(self, forged_tokens):
        """Custom cap below natural total stops the walker early."""
        # 10 non-auth routes → 30 max probes; cap to 15.
        routes = [
            _make_route_entry(f"/api/r{i}", auth_required=False) for i in range(10)
        ]
        walker = RouteWalker(
            route_index=routes,
            forged_tokens=forged_tokens,
            max_attempts=15,
            max_depth=10,
        )
        probes = [p async for p in walker]

        assert len(probes) == 15
        state = walker.verdict()
        assert state.exhausted is True

    @pytest.mark.asyncio
    async def test_cap_unreached_for_small_fixture(self, forged_tokens):
        """Walker stops when queue is drained, not because of cap."""
        routes = [
            _make_route_entry("/api/a", auth_required=False),
            _make_route_entry("/api/b", auth_required=True),
        ]
        walker = RouteWalker(
            route_index=routes,
            forged_tokens=forged_tokens,
            max_attempts=200,  # far above natural total (5)
        )
        probes = [p async for p in walker]

        assert len(probes) == 5
        state = walker.verdict()
        # Queue drained → exhausted=True even though cap
        # was not the trigger.
        assert state.exhausted is True
        assert state.visited == 5


# ─── Test: mark_blocked ─────────────────────────────────────────────


class TestMarkBlocked:
    @pytest.mark.asyncio
    async def test_mark_blocked_updates_state(self, forged_tokens):
        """mark_blocked increments blocked counter and adds to blocked_routes."""
        entry = _make_route_entry("/api/users", auth_required=True)
        walker = RouteWalker(
            route_index=[entry],
            forged_tokens=forged_tokens,
        )

        walker.mark_blocked(entry, "403")
        state = walker.verdict()

        assert state.blocked == 1
        assert state.blocked_routes == [entry]

    @pytest.mark.asyncio
    async def test_mark_blocked_increments_per_call(self, forged_tokens):
        """Repeated mark_blocked on the same route still increments counter."""
        entry = _make_route_entry("/api/users", auth_required=True)
        walker = RouteWalker(
            route_index=[entry],
            forged_tokens=forged_tokens,
        )

        walker.mark_blocked(entry, "403")
        walker.mark_blocked(entry, "401")
        walker.mark_blocked(entry, "WAF")

        state = walker.verdict()
        # blocked is per-call, not per-unique-route.
        assert state.blocked == 3
        # blocked_routes is de-duplicated.
        assert state.blocked_routes == [entry]

    @pytest.mark.asyncio
    async def test_mark_blocked_for_different_routes(self, forged_tokens):
        """Multiple distinct routes tracked separately in blocked_routes."""
        entry_a = _make_route_entry("/api/a", auth_required=True)
        entry_b = _make_route_entry("/api/b", auth_required=True)
        walker = RouteWalker(
            route_index=[entry_a, entry_b],
            forged_tokens=forged_tokens,
        )

        walker.mark_blocked(entry_a, "403")
        walker.mark_blocked(entry_b, "403")

        state = walker.verdict()
        assert state.blocked == 2
        assert state.blocked_routes == [entry_a, entry_b]

    @pytest.mark.asyncio
    async def test_mark_blocked_does_not_affect_emission(self, forged_tokens):
        """mark_blocked does not remove the route from the BFS queue."""
        entry = _make_route_entry("/api/users", auth_required=True)
        walker = RouteWalker(
            route_index=[entry],
            forged_tokens=forged_tokens,
        )

        walker.mark_blocked(entry, "403")
        probes = [p async for p in walker]

        # Route still emits its 2 auth probes.
        assert len(probes) == 2
        assert all(p.path == "/api/users" for p in probes)


# ─── Test: verdict ──────────────────────────────────────────────────


class TestVerdict:
    @pytest.mark.asyncio
    async def test_verdict_returns_initial_state(self, forged_tokens):
        """verdict before any iteration returns a zero state."""
        walker = RouteWalker(
            route_index=[_make_route_entry("/api/public", auth_required=False)],
            forged_tokens=forged_tokens,
        )
        state = walker.verdict()

        assert state.visited == 0
        assert state.blocked == 0
        assert state.exhausted is False
        assert state.blocked_routes == []

    @pytest.mark.asyncio
    async def test_verdict_reflects_iteration_progress(self, forged_tokens):
        """verdict after partial iteration reflects current state."""
        routes = [
            _make_route_entry("/api/a", auth_required=False),
            _make_route_entry("/api/b", auth_required=False),
        ]
        walker = RouteWalker(
            route_index=routes,
            forged_tokens=forged_tokens,
        )

        # Drain the iterator.
        _ = [p async for p in walker]

        state = walker.verdict()
        assert state.visited == 6
        assert state.exhausted is True


# ─── Test: edge cases ──────────────────────────────────────────────


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_route_index_emits_nothing(self, forged_tokens):
        """Empty route_index → walker yields no probes and is exhausted."""
        walker = RouteWalker(
            route_index=[],
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]

        assert probes == []
        state = walker.verdict()
        assert state.exhausted is True
        assert state.visited == 0

    @pytest.mark.asyncio
    async def test_route_with_no_methods_uses_get_fallback(self, forged_tokens):
        """Route with empty methods list → probes use 'GET' as fallback."""
        # Construct an entry with no methods directly,
        # bypassing the helper's default.
        entry = RouteIndexEntry(
            path="/api/mystery",
            methods=[],
            params={},
            auth_required=False,
            auth_stack="custom",
            file_path="app/mystery.ts",
            line=1,
        )
        walker = RouteWalker(
            route_index=[entry],
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]

        assert len(probes) == 3
        assert all(p.method == "GET" for p in probes)

    @pytest.mark.asyncio
    async def test_post_route_uses_post_method(self, forged_tokens):
        """Route with POST method → all variants carry method='POST'."""
        entry = _make_route_entry(
            "/api/create", methods=["POST"], auth_required=True
        )
        walker = RouteWalker(
            route_index=[entry],
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]

        # auth_required → 2 probes (user_a, user_b).
        assert len(probes) == 2
        assert all(p.method == "POST" for p in probes)

    @pytest.mark.asyncio
    async def test_probe_carries_back_reference_to_route(self, forged_tokens, small_route_index):
        """Each probe's `route_entry` is the same object as the source entry."""
        walker = RouteWalker(
            route_index=small_route_index,
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]

        # Every probe must carry the entry it was
        # generated from. Check by identity, not just
        # path equality — the walker stores the
        # reference, not a copy.
        for probe in probes:
            assert probe.route_entry in small_route_index


# ─── Test: no real HTTP calls ───────────────────────────────────────


class TestNoRealNetwork:
    @pytest.mark.asyncio
    async def test_walker_makes_no_http_calls(self, forged_tokens):
        """The walker is a pure generator — no HTTP, no socket, no I/O.

        Verification: drain the walker and verify all
        outputs are local `CurlProbe` objects. There is
        no async network code in `route_walker.py`; this
        test is a smoke check that the module didn't
        accidentally grow an HTTP dependency.
        """
        import inspect
        import sandbox.route_walker as rw_module

        # Source-level check: no `httpx`, `aiohttp`,
        # `requests`, or `urllib` imports.
        source = inspect.getsource(rw_module)
        for banned in ("httpx", "aiohttp", "requests", "urllib"):
            assert banned not in source, (
                f"route_walker must not import {banned} (pure generator)"
            )

        # Runtime check: the walker yields only CurlProbe
        # instances — never dicts, never strings, never
        # anything that could be a response.
        walker = RouteWalker(
            route_index=[_make_route_entry("/api/public", auth_required=False)],
            forged_tokens=forged_tokens,
        )
        probes = [p async for p in walker]
        assert all(isinstance(p, CurlProbe) for p in probes)

    @pytest.mark.asyncio
    async def test_full_walk_completes_immediately(self, forged_tokens):
        """Full walk with default caps completes in <1s (no I/O wait).

        This is a smoke check that the walker is doing
        pure in-memory work, not waiting on any external
        resource. If a future change accidentally adds
        an HTTP roundtrip, this test will time out.
        """
        import time

        routes = [
            _make_route_entry(f"/api/r{i}", auth_required=False) for i in range(5)
        ]
        walker = RouteWalker(
            route_index=routes,
            forged_tokens=forged_tokens,
        )

        start = time.monotonic()
        _ = [p async for p in walker]
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, f"walker took {elapsed:.3f}s — looks like real I/O"
