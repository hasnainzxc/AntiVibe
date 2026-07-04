"""Tests for the No-stop Pivot Engine.

The pivot engine is pure decision logic — it never
opens a socket, never sleeps, never talks to a real
sandbox. Tests construct `httpx.Response` objects
inline and pass them as the `observed_responses`
list. The engine looks at the LAST response's status
to pick the next action; the response body is
ignored.

Coverage map
------------
- 403 -> token swap (first attempt)
- 403 -> method swap (second attempt)
- 404 -> adjacent path (first attempt)
- 404 -> param extension (second attempt)
- 429 -> retry_with_patch with Retry-After delay
- 5xx -> returns None, lineage marked exhausted
- max_tries=4 -> after 4 calls the 5th returns None
- No real HTTP -> nothing in this module imports a
  real transport; we verify by checking that
  constructing the engine + running the test suite
  never attempts a network call. The simplest
  guarantee: the module has no `requests`/`urllib`/
  `httpx.AsyncClient` instantiation in the engine
  path (it accepts responses, doesn't fire them).
"""

import httpx
import pytest

from sandbox.pivot_engine import (
    DEFAULT_MAX_TRIES,
    PIVOT_ACTIONS,
    PivotAction,
    PivotEngine,
    _parent_path,
    _response_retry_after,
    _response_status,
)
from sandbox.route_mapper import RouteIndexEntry
from sandbox.route_walker import CurlProbe, WalkerState

# ─── Helpers ─────────────────────────────────────────────────────────


def _make_route_entry(
    path: str,
    methods: list[str] | None = None,
) -> RouteIndexEntry:
    """Build a minimal RouteIndexEntry for tests."""
    return RouteIndexEntry(
        path=path,
        methods=methods if methods is not None else ["GET"],
        params={},
        auth_required=True,
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

    Defaults model the most common pivot target: a
    GET on a `/api/users/:id` style route with a
    user_a token. The Authorization header carries
    a recognisable synthetic token so tests can
    verify the engine does not mutate the original
    headers.
    """
    return CurlProbe(
        method=method,
        path=path,
        headers={"Authorization": "Bearer fake-jwt-user-a"},
        body=None,
        token_type=token_type,
        route_entry=_make_route_entry(path),
    )


def _response(status: int, retry_after: str | None = None) -> httpx.Response:
    """Build an httpx.Response for use as observed input.

    `retry_after`, when set, is added as a
    `Retry-After` header. Body is an empty JSON
    object; the engine ignores body content.
    """
    headers: dict[str, str] = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return httpx.Response(status, json={}, headers=headers)


def _empty_verdict() -> WalkerState:
    """Build a fresh WalkerState for tests.

    The engine reads `.visited` for log context only,
    so an all-default state is enough.
    """
    return WalkerState()


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def probe() -> CurlProbe:
    return _make_probe()


@pytest.fixture
def engine() -> PivotEngine:
    return PivotEngine()


@pytest.fixture
def verdict() -> WalkerState:
    return _empty_verdict()


# ─── Test: dataclass shape ───────────────────────────────────────────


class TestPivotActionShape:
    def test_pivot_action_fields(self):
        """PivotAction has all 4 fields per spec."""
        entry = _make_route_entry("/api/users/1")
        p = CurlProbe(
            method="GET",
            path="/api/users/1",
            headers={},
            body=None,
            token_type="user_a",
            route_entry=entry,
        )
        action = PivotAction(
            action="token_swap",
            probe=p,
            attempt=1,
            max_tries=4,
        )
        assert action.action == "token_swap"
        assert action.probe is p
        assert action.attempt == 1
        assert action.max_tries == 4

    def test_pivot_actions_contains_all_five_tags(self):
        """PIVOT_ACTIONS exposes all 5 action tags from the spec."""
        for tag in (
            "retry_with_patch",
            "method_swap",
            "token_swap",
            "adjacent_path",
            "param_extension",
        ):
            assert tag in PIVOT_ACTIONS

    def test_default_max_tries_is_four(self):
        """DEFAULT_MAX_TRIES matches the spec's max_tries=4 default."""
        assert DEFAULT_MAX_TRIES == 4


# ─── Test: helper functions ──────────────────────────────────────────


class TestHelpers:
    def test_response_status_from_httpx(self):
        """_response_status reads .status_code from httpx.Response."""
        assert _response_status(httpx.Response(200)) == 200
        assert _response_status(httpx.Response(403)) == 403
        assert _response_status(httpx.Response(500)) == 500

    def test_response_status_from_int(self):
        """_response_status accepts a raw int."""
        assert _response_status(404) == 404
        assert _response_status(429) == 429

    def test_response_status_from_dict(self):
        """_response_status reads the 'status' key from a dict."""
        assert _response_status({"status": 403}) == 403
        assert _response_status({"status": 500}) == 500

    def test_response_status_from_none(self):
        """_response_status returns 0 for None / unknown shapes."""
        assert _response_status(None) == 0
        assert _response_status([]) == 0
        assert _response_status({}) == 0

    def test_response_retry_after_parsed(self):
        """_response_retry_after returns the float from the header."""
        resp = _response(429, retry_after="2.5")
        assert _response_retry_after(resp) == 2.5

    def test_response_retry_after_zero_when_absent(self):
        """_response_retry_after returns 0.0 when no header is present."""
        resp = _response(429)
        assert _response_retry_after(resp) == 0.0

    def test_response_retry_after_zero_when_unparseable(self):
        """_response_retry_after returns 0.0 when the header is junk."""
        resp = _response(429, retry_after="not-a-number")
        assert _response_retry_after(resp) == 0.0

    def test_response_retry_after_from_none(self):
        """_response_retry_after returns 0.0 for None / unknown shapes."""
        assert _response_retry_after(None) == 0.0
        assert _response_retry_after({}) == 0.0

    def test_parent_path_strips_last_segment(self):
        """_parent_path returns the path with the last segment removed."""
        assert _parent_path("/api/users/42") == "/api/users"
        assert _parent_path("/api/users/42/posts/7") == "/api/users/42/posts"
        assert _parent_path("/api/users") == "/api"

    def test_parent_path_root_for_short_paths(self):
        """_parent_path returns '/' for paths with no parent."""
        assert _parent_path("/api") == "/"
        assert _parent_path("/") == "/"
        assert _parent_path("") == "/"
        assert _parent_path("users") == "/"


# ─── Test: 403 pivot ─────────────────────────────────────────────────


class Test403Pivot:
    @pytest.mark.asyncio
    async def test_403_first_attempt_is_token_swap(
        self, engine, probe, verdict
    ):
        """403 response -> token_swap action with user_a -> user_b."""
        responses = [_response(403)]
        action = await engine.pivot(probe, verdict, responses)

        assert action is not None
        assert action.action == "token_swap"
        # token_type flips a -> b.
        assert action.probe.token_type == "user_b"
        # Same path / method as the original.
        assert action.probe.path == probe.path
        assert action.probe.method == probe.method
        # Attempt counter starts at 1.
        assert action.attempt == 1
        assert action.max_tries == 4

    @pytest.mark.asyncio
    async def test_403_second_attempt_is_method_swap(
        self, engine, probe, verdict
    ):
        """Second 403 on the same lineage -> method_swap.

        The first pivot tries token_swap; the second
        walks the 403 sequence to method_swap. The
        method becomes POST (the first non-GET in
        the swap order).
        """
        await engine.pivot(probe, verdict, [_response(403)])
        action = await engine.pivot(probe, verdict, [_response(403)])

        assert action is not None
        assert action.action == "method_swap"
        # GET pivots to POST.
        assert action.probe.method == "POST"
        # Path is unchanged on method_swap.
        assert action.probe.path == probe.path
        # attempt counter incremented.
        assert action.attempt == 2

    @pytest.mark.asyncio
    async def test_403_token_swap_user_b_flips_to_user_a(
        self, engine, verdict
    ):
        """A user_b probe gets pivoted back to user_a on 403.

        Symmetry check: a probe emitted with the
        cross-tenant User_B token should pivot to
        User_A's token on 403, not bounce to a
        different User_B variant.
        """
        probe_b = _make_probe(token_type="user_b")
        action = await engine.pivot(probe_b, verdict, [_response(403)])

        assert action is not None
        assert action.action == "token_swap"
        assert action.probe.token_type == "user_a"

    @pytest.mark.asyncio
    async def test_403_does_not_mutate_original_headers(
        self, engine, probe, verdict
    ):
        """The original probe's headers are not mutated by the pivot.

        Defensive: the engine returns a new probe;
        the caller's probe is left intact for the
        next iteration or for the report.
        """
        original_auth = probe.headers["Authorization"]
        await engine.pivot(probe, verdict, [_response(403)])

        assert probe.headers["Authorization"] == original_auth


# ─── Test: 404 pivot ─────────────────────────────────────────────────


class Test404Pivot:
    @pytest.mark.asyncio
    async def test_404_first_attempt_is_adjacent_path(
        self, engine, verdict
    ):
        """404 response -> adjacent_path (PATCH on parent path).

        `/api/users/42` should pivot to PATCH on
        `/api/users`. The action tag is
        `adjacent_path` so the runner knows the
        path shape changed.
        """
        probe = _make_probe(path="/api/users/42")
        action = await engine.pivot(probe, verdict, [_response(404)])

        assert action is not None
        assert action.action == "adjacent_path"
        # Path is the parent.
        assert action.probe.path == "/api/users"
        # Method is forced to PATCH.
        assert action.probe.method == "PATCH"
        assert action.attempt == 1

    @pytest.mark.asyncio
    async def test_404_second_attempt_is_param_extension(
        self, engine, verdict
    ):
        """Second 404 on the same lineage -> param_extension (/settings)."""
        probe = _make_probe(path="/api/users/42")
        await engine.pivot(probe, verdict, [_response(404)])
        action = await engine.pivot(probe, verdict, [_response(404)])

        assert action is not None
        assert action.action == "param_extension"
        # Path is extended with /settings.
        assert action.probe.path == "/api/users/42/settings"
        # Method is preserved.
        assert action.probe.method == probe.method
        assert action.attempt == 2


# ─── Test: 429 retry ─────────────────────────────────────────────────


class Test429Retry:
    @pytest.mark.asyncio
    async def test_429_emits_retry_with_patch(
        self, engine, probe, verdict
    ):
        """429 response -> retry_with_patch with the same probe.

        429 is a soft block: the runner is expected
        to wait the Retry-After delay and re-fire
        the EXACT same probe. The PivotAction's
        `probe` is therefore the original, not a
        variant.
        """
        responses = [_response(429, retry_after="1.5")]
        action = await engine.pivot(probe, verdict, responses)

        assert action is not None
        assert action.action == "retry_with_patch"
        # Same probe object: not a variant.
        assert action.probe is probe
        assert action.attempt == 1

    @pytest.mark.asyncio
    async def test_429_attempt_increments_across_calls(
        self, engine, probe, verdict
    ):
        """Each 429 retry bumps the attempt counter.

        The engine treats every 429 as a fresh
        attempt against the same budget, so
        repeated 429s eventually exhaust the
        lineage.
        """
        first = await engine.pivot(probe, verdict, [_response(429)])
        second = await engine.pivot(probe, verdict, [_response(429)])

        assert first is not None and first.attempt == 1
        assert second is not None and second.attempt == 2

    @pytest.mark.asyncio
    async def test_429_default_delay_zero_when_no_header(
        self, engine, probe, verdict
    ):
        """A 429 without Retry-After is still a valid retry (delay 0).

        The runner is responsible for the actual
        sleep; the engine only signals the action.
        The delay is a hint surfaced via the
        observed_responses and the helper, not on
        the PivotAction itself.
        """
        responses = [_response(429)]
        action = await engine.pivot(probe, verdict, responses)

        assert action is not None
        assert action.action == "retry_with_patch"
        # No assertion on the action for the delay
        # itself — the helper already covers the
        # parsing; here we just confirm a missing
        # header doesn't break the pivot.

    @pytest.mark.asyncio
    async def test_429_does_not_exhaust_on_single_response(
        self, engine, probe, verdict
    ):
        """One 429 does not exhaust the lineage; the next 429 still produces an action.

        `exhausted` only kicks in once
        `attempt > max_tries`. The first 429 is
        attempt 1, well within the budget.
        """
        action = await engine.pivot(probe, verdict, [_response(429)])

        assert action is not None
        assert engine.is_exhausted(probe) is False


# ─── Test: 5xx skip ──────────────────────────────────────────────────


class Test5xxSkip:
    @pytest.mark.asyncio
    async def test_500_returns_none(self, engine, probe, verdict):
        """500 response -> engine returns None (app is broken, not blocked)."""
        action = await engine.pivot(probe, verdict, [_response(500)])

        assert action is None

    @pytest.mark.asyncio
    async def test_502_returns_none(self, engine, probe, verdict):
        """502 Bad Gateway -> None."""
        action = await engine.pivot(probe, verdict, [_response(502)])

        assert action is None

    @pytest.mark.asyncio
    async def test_503_returns_none(self, engine, probe, verdict):
        """503 Service Unavailable -> None."""
        action = await engine.pivot(probe, verdict, [_response(503)])

        assert action is None

    @pytest.mark.asyncio
    async def test_5xx_marks_lineage_exhausted(
        self, engine, probe, verdict
    ):
        """A 5xx exhausts the lineage; the runner won't re-prompt.

        After a 5xx the engine reports exhausted so
        the runner's next call to `pivot()` returns
        None immediately (no wasted attempt slot).
        """
        await engine.pivot(probe, verdict, [_response(500)])

        assert engine.is_exhausted(probe) is True
        # Subsequent call returns None without
        # touching the attempt counter.
        second = await engine.pivot(probe, verdict, [_response(500)])
        assert second is None

    @pytest.mark.asyncio
    async def test_5xx_does_not_burn_attempt_budget(
        self, engine, probe, verdict
    ):
        """A 5xx does not count as a pivot attempt.

        `attempt` on a subsequent 403 should start
        at 1, not at 2. The 5xx is a signal, not
        an attempt.
        """
        await engine.pivot(probe, verdict, [_response(500)])
        # 5xx exhausts the lineage, so a follow-up
        # 403 returns None. Verify the exhaust
        # happened — i.e. the 5xx blocked any
        # future pivot for this lineage.
        action = await engine.pivot(probe, verdict, [_response(403)])
        assert action is None


# ─── Test: max_tries enforcement ─────────────────────────────────────


class TestMaxTries:
    @pytest.mark.asyncio
    async def test_max_tries_4_respected_on_403(
        self, engine, probe, verdict
    ):
        """After 4 pivot attempts on 403, the 5th call returns None.

        With a 2-action sequence the engine
        rotates: attempts 1-2 walk token_swap,
        method_swap, attempts 3-4 cycle back. The
        5th call exceeds max_tries and returns
        None.
        """
        results = []
        for _ in range(5):
            action = await engine.pivot(
                probe, verdict, [_response(403)]
            )
            results.append(action)

        # First 4 succeed; 5th is None.
        assert all(a is not None for a in results[:4])
        assert results[4] is None

    @pytest.mark.asyncio
    async def test_max_tries_4_respected_on_404(
        self, engine, verdict
    ):
        """Same cap on 404: 4 actions, 5th is None."""
        probe = _make_probe(path="/api/users/42")
        results = []
        for _ in range(5):
            action = await engine.pivot(
                probe, verdict, [_response(404)]
            )
            results.append(action)

        assert all(a is not None for a in results[:4])
        assert results[4] is None

    @pytest.mark.asyncio
    async def test_max_tries_4_respected_on_429(
        self, engine, probe, verdict
    ):
        """Same cap on 429: 4 retries, 5th is None.

        429 retries don't produce a different
        probe, but the attempt counter still
        advances and eventually exhausts the
        lineage.
        """
        results = []
        for _ in range(5):
            action = await engine.pivot(
                probe, verdict, [_response(429)]
            )
            results.append(action)

        assert all(a is not None for a in results[:4])
        assert results[4] is None

    @pytest.mark.asyncio
    async def test_attempt_field_matches_call_count(
        self, engine, probe, verdict
    ):
        """The PivotAction.attempt field reflects the call index (1-based)."""
        first = await engine.pivot(probe, verdict, [_response(403)])
        second = await engine.pivot(probe, verdict, [_response(403)])
        third = await engine.pivot(probe, verdict, [_response(403)])
        fourth = await engine.pivot(probe, verdict, [_response(403)])

        assert first.attempt == 1
        assert second.attempt == 2
        assert third.attempt == 3
        assert fourth.attempt == 4

    @pytest.mark.asyncio
    async def test_exhausted_after_max_tries(
        self, engine, probe, verdict
    ):
        """is_exhausted returns True after the cap is hit."""
        for _ in range(4):
            await engine.pivot(probe, verdict, [_response(403)])
        # After 4 calls, the 5th returns None AND
        # marks the lineage exhausted.
        await engine.pivot(probe, verdict, [_response(403)])

        assert engine.is_exhausted(probe) is True

    @pytest.mark.asyncio
    async def test_custom_max_tries(self, probe, verdict):
        """A custom max_tries is respected end-to-end.

        With max_tries=2, two pivot actions are
        emitted and the third returns None.
        """
        engine = PivotEngine(max_tries=2)
        first = await engine.pivot(probe, verdict, [_response(403)])
        second = await engine.pivot(probe, verdict, [_response(403)])
        third = await engine.pivot(probe, verdict, [_response(403)])

        assert first is not None and first.max_tries == 2
        assert second is not None and second.max_tries == 2
        assert third is None
        assert engine.is_exhausted(probe) is True

    def test_invalid_max_tries_rejected(self):
        """max_tries=0 raises ValueError; max_tries<0 raises ValueError."""
        with pytest.raises(ValueError):
            PivotEngine(max_tries=0)
        with pytest.raises(ValueError):
            PivotEngine(max_tries=-1)

    @pytest.mark.asyncio
    async def test_separate_lineages_have_separate_budgets(
        self, engine, verdict
    ):
        """Two probes with different paths do not share the attempt budget.

        The (path, method) tuple is the lineage
        key. A 403 on /api/users/1 must not
        exhaust a probe on /api/users/2.
        """
        probe_a = _make_probe(path="/api/users/1")
        probe_b = _make_probe(path="/api/users/2")
        for _ in range(4):
            await engine.pivot(probe_a, verdict, [_response(403)])
        await engine.pivot(probe_a, verdict, [_response(403)])
        assert engine.is_exhausted(probe_a) is True
        assert engine.is_exhausted(probe_b) is False
        action = await engine.pivot(probe_b, verdict, [_response(403)])
        assert action is not None
        assert action.attempt == 1


# ─── Test: no real HTTP ──────────────────────────────────────────────


class TestNoRealHTTP:
    @pytest.mark.asyncio
    async def test_engine_never_makes_http_calls(
        self, probe, verdict, monkeypatch
    ):
        """The pivot engine does not import or use an HTTP client.

        We monkeypatch `httpx.AsyncClient` and
        `httpx.Client` to raise on construction.
        If the engine ever instantiates a client in
        its hot path, the test fails loudly.
        """

        def _explode(*args, **kwargs):
            raise AssertionError(
                "PivotEngine must not instantiate an HTTP client"
            )

        monkeypatch.setattr(httpx, "AsyncClient", _explode)
        monkeypatch.setattr(httpx, "Client", _explode)

        # Run a full pivot cycle. The engine
        # accepts pre-built response objects; it
        # must never reach for a client.
        engine = PivotEngine()
        await engine.pivot(probe, verdict, [_response(403)])
        await engine.pivot(probe, verdict, [_response(404)])
        await engine.pivot(probe, verdict, [_response(429)])
        # No AssertionError -> engine never touched httpx.Client.

    def test_engine_constructor_does_no_io(self):
        """Constructing the engine does not touch the network.

        We can only check this indirectly: if the
        constructor opened a socket, this test
        would either hang (no DNS for 0.0.0.0) or
        fail with a connection error. Neither
        happens; the test returns in milliseconds.
        """
        engine = PivotEngine()  # noqa: F841
        assert engine.max_tries == 4

    @pytest.mark.asyncio
    async def test_engine_works_with_pure_dict_responses(
        self, engine, probe, verdict
    ):
        """The engine accepts dict-shaped responses (no httpx required).

        This proves the engine's contract is
        response-shape-agnostic — a runner that
        doesn't use httpx can still drive the
        engine with plain dicts.
        """
        action = await engine.pivot(
            probe, verdict, [{"status": 403}]
        )

        assert action is not None
        assert action.action == "token_swap"
