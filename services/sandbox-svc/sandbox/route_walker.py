"""Route Walker for Tier 3 Fuzz Agent.

Architecture
------------
This module is the *generator* half of the Tier 3 fuzzer.
It takes the Tier 2 outputs (route index + forged tokens)
and produces a stream of `CurlProbe` instances to fire at
the live sandbox. The runner is the *consumer* half; this
module deliberately knows nothing about HTTP — it just
emits probes in BFS order.

BFS over the route index
------------------------
A flat route index is naturally BFS-ready: the list *is*
the breadth-first traversal. The walker pops routes in
list order and, for each route, emits up to three probes
(one per token variant). The walk is bounded by two caps:

    - `max_attempts` (default 200): total probes emitted.
      Hard stop — once visited reaches the cap, the
      iterator raises `StopAsyncIteration` even if there
      are unvisited routes left in the queue.
    - `max_depth` (default 5): number of distinct routes
      pulled from the head of `route_index`. For a flat
      index, "BFS depth" maps 1:1 to "route position",
      so `max_depth=5` means "process at most the first
      5 routes in the list".

Token variant emission
----------------------
For each route, the walker emits up to three probes in a
deterministic order:

    1. tokenless  — no Authorization header. Detects
                    routes that should require auth but
                    don't (open-API surface).
    2. user_a     — Bearer token for the cross-tenant
                    pivot user. Tests for BOLA.
    3. user_b     — Bearer token for the other tenant.
                    Tests for BOLA in the reverse
                    direction.

When `route.auth_required=True`, the tokenless probe is
skipped. Sending no auth to a known-auth route just
guarantees a 401/403 — no signal, no value, wastes an
attempt slot.

Why an async iterator, not a list
---------------------------------
The runner consumes one probe at a time. A list would
force the runner to either drain everything upfront (no
backpressure against a slow endpoint) or manually manage
an index. An async iterator gives the runner backpressure
for free: when the network is slow, the walker simply
yields slowly.

`mark_blocked` is non-destructive
---------------------------------
Calling `mark_blocked` records the block in `WalkerState`
but does *not* remove the route from the BFS queue. The
runner may want to pivot on a blocked route (try a
different method, header, or token) — removing the route
from the queue would prevent that. The blocked metric
is for the report, not for control flow.

Dependency map
--------------
- Reads from: `sandbox.route_mapper.RouteIndexEntry`,
              `sandbox.jwt_forge.ForgedToken`.
- Writes to: nothing; pure generator.
- Consumed by: the Tier 3 fuzzer runner (not yet
              implemented; this is the generator side of
              the fuzzer pair).

Testing
-------
- `tests/sandbox/test_route_walker.py` covers: 200-cap
  enforcement, three-variant emission for non-auth
  routes, tokenless-skip for auth routes, mark_blocked
  state updates, BFS ordering across a multi-route
  fixture, and a "no real HTTP" smoke test.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional, AsyncIterator

import structlog

from sandbox.route_mapper import RouteIndexEntry
from sandbox.jwt_forge import ForgedToken

logger = structlog.get_logger(__name__)


@dataclass
class CurlProbe:
    """One HTTP probe to fire at the sandbox.

    Fields:
        method:       HTTP verb (GET, POST, etc.). Pulled
                      from `route_entry.methods[0]`; falls
                      back to "GET" when the route shape
                      didn't expose a method.
        path:         The normalized path from
                      `route_entry.path` (e.g. `/api/users/:id`).
        headers:      Dict of HTTP headers. Includes an
                      `Authorization: Bearer <jwt>` line
                      when `token_type != "none"`. Empty
                      dict for tokenless probes.
        body:         Request body. `None` for tokenless
                      GETs. The runner is free to mutate
                      this for POST/PUT bodies.
        token_type:   "none" | "user_a" | "user_b". The
                      runner uses this to log which token
                      was used and to cross-tab findings
                      against the tenant.
        route_entry:  Back-reference to the source
                      `RouteIndexEntry` for cross-stage
                      correlation (route → finding).
    """

    method: str
    path: str
    headers: dict = field(default_factory=dict)
    body: Optional[str] = None
    token_type: str = "none"
    route_entry: Optional[RouteIndexEntry] = None


@dataclass
class WalkerState:
    """Snapshot of the walker's progress.

    Fields:
        visited:        Count of probes yielded so far.
                        Monotonic — only increments.
        blocked:        Count of routes that received a
                        block signal. Set by
                        `RouteWalker.mark_blocked`. A
                        single route can be marked blocked
                        multiple times (e.g. 401 on
                        tokenless, 403 on user_a); each
                        call increments this counter.
        exhausted:      True when the BFS queue is drained
                        *or* the attempt cap is reached.
                        The runner checks this to know
                        when to stop consuming.
        blocked_routes: List of `RouteIndexEntry` refs
                        that were marked blocked at least
                        once. De-duplicated: a route
                        marked blocked twice appears once
                        here. Order is insertion order.
    """

    visited: int = 0
    blocked: int = 0
    exhausted: bool = False
    blocked_routes: list = field(default_factory=list)


class RouteWalker:
    """BFS-based async iterator that yields curl probes.

    The walker is stateful. It tracks `WalkerState` in
    `self._state` and updates it as probes are yielded
    and blocks are recorded. A snapshot is returned by
    `verdict()` at any time.

    Args:
        route_index:    List of `RouteIndexEntry` from the
                        route mapper. Order is preserved —
                        BFS visits in list order.
        forged_tokens:  Tuple `(token_a, token_b)` from
                        `jwt_forge.forge()`. The walker
                        extracts the raw JWT string from
                        each `ForgedToken`. Order matters:
                        `token_a` becomes the "user_a"
                        probe, `token_b` becomes "user_b".
        max_attempts:   Cap on total probes emitted.
                        Default 200 — matches the
                        task-spec value.
        max_depth:      Cap on the number of routes
                        processed in the BFS. Default 5.
                        With a flat list, this is the
                        max number of routes pulled
                        from the head of `route_index`.

    Usage:
        walker = RouteWalker(routes, (token_a, token_b))
        async for probe in walker:
            response = await fire(probe)
            if response.status in (401, 403):
                walker.mark_blocked(probe.route_entry, str(response.status))

        state = walker.verdict()
        # state.visited, state.blocked, state.exhausted, state.blocked_routes
    """

    def __init__(
        self,
        route_index: list[RouteIndexEntry],
        forged_tokens: tuple[ForgedToken, ForgedToken],
        max_attempts: int = 200,
        max_depth: int = 5,
    ):
        self.route_index = route_index
        self.forged_tokens = forged_tokens
        self.max_attempts = max_attempts
        self.max_depth = max_depth

        # BFS queue — depth-capped. For a flat list, BFS
        # is the same as sequential iteration; the
        # `max_depth` cap just bounds how many distinct
        # routes we ever look at. A `route_index` of 10
        # with `max_depth=5` → first 5 routes only.
        self._queue: list[RouteIndexEntry] = list(route_index[:max_depth])

        # Iterator state. `_entry_idx` and `_probe_idx`
        # together track position in the 2D
        # (route × variant) emission matrix.
        self._state = WalkerState()
        self._entry_idx = 0
        self._probe_idx = 0
        self._current_probes: list[CurlProbe] = []

    def __aiter__(self) -> AsyncIterator[CurlProbe]:
        return self

    async def __anext__(self) -> CurlProbe:
        # Termination: attempt cap reached.
        # Checked first because the cap is the most
        # common reason to stop in a real scan.
        if self._state.visited >= self.max_attempts:
            self._state.exhausted = True
            raise StopAsyncIteration

        # Termination: BFS queue drained.
        if self._entry_idx >= len(self._queue):
            self._state.exhausted = True
            raise StopAsyncIteration

        # Lazily build the probe list for the current
        # route. Built once per route, then drained
        # variant-by-variant.
        if not self._current_probes:
            entry = self._queue[self._entry_idx]
            self._current_probes = self._build_probes_for(entry)
            self._probe_idx = 0

        # If the current route emits zero probes (e.g. a
        # malformed entry with no methods AND no
        # injectable body), skip to the next entry. In
        # practice every entry produces ≥ 2 probes
        # (user_a + user_b), so this branch is defensive
        # only.
        if self._probe_idx >= len(self._current_probes):
            self._entry_idx += 1
            self._current_probes = []
            return await self.__anext__()

        # Yield the next probe.
        probe = self._current_probes[self._probe_idx]
        self._probe_idx += 1
        self._state.visited += 1

        # If we just emitted the last probe for this
        # route, advance `_entry_idx` so the *next*
        # `__anext__` call starts on the following
        # route. The advance happens at yield time
        # rather than at entry-change time so the
        # recursion in the "zero probes" branch above
        # is unambiguous.
        if self._probe_idx >= len(self._current_probes):
            self._entry_idx += 1
            self._current_probes = []

        return probe

    def _build_probes_for(self, entry: RouteIndexEntry) -> list[CurlProbe]:
        """Build the probe list for a single route.

        Emission order is deterministic:

            1. tokenless (when `not entry.auth_required`)
            2. user_a
            3. user_b

        This order is load-bearing: the "BFS emits all
        routes in fixture" test asserts that the
        sequence of `(path, token_type)` pairs follows
        this rule across the whole route list.

        Args:
            entry: The current `RouteIndexEntry`.

        Returns:
            List of `CurlProbe`, length 2 (auth route)
            or 3 (non-auth route).
        """
        probes: list[CurlProbe] = []
        token_a, token_b = self.forged_tokens
        # `entry.methods` is the parsed list of HTTP
        # verbs. The walker emits one probe per (route,
        # variant) pair — the runner may fan out into
        # more methods later, but the walker's contract
        # is "one probe per (route, token)".
        method = entry.methods[0] if entry.methods else "GET"

        # Tokenless probe: only when the route is not
        # known to require auth. A 401 from an
        # auth-required route is a known-no-signal
        # outcome; spending an attempt slot on it
        # burns cap budget.
        if not entry.auth_required:
            probes.append(CurlProbe(
                method=method,
                path=entry.path,
                headers={},
                body=None,
                token_type="none",
                route_entry=entry,
            ))

        # User_A probe: always emitted. Bearer header
        # uses the raw `ForgedToken.token` string.
        probes.append(CurlProbe(
            method=method,
            path=entry.path,
            headers={"Authorization": f"Bearer {token_a.token}"},
            body=None,
            token_type="user_a",
            route_entry=entry,
        ))

        # User_B probe: always emitted. Same shape as
        # user_a but with the cross-tenant token.
        probes.append(CurlProbe(
            method=method,
            path=entry.path,
            headers={"Authorization": f"Bearer {token_b.token}"},
            body=None,
            token_type="user_b",
            route_entry=entry,
        ))

        return probes

    def mark_blocked(self, entry: RouteIndexEntry, reason: str) -> None:
        """Record that a route was blocked.

        The route is NOT removed from the BFS queue.
        A blocked route may still be probed with a
        different variant (e.g. user_a blocked →
        pivot to user_b), and the runner's pivot logic
        needs the route to remain in scope.

        The `blocked` counter increments on every call
        (a route can be blocked twice — once for each
        token variant), but `blocked_routes` is
        de-duplicated: a route appears at most once.

        Args:
            entry:  The `RouteIndexEntry` that was blocked.
            reason: Short string describing the block
                    (e.g. "403", "WAF", "rate-limit").
                    Logged for the audit trail; not
                    stored on the state object.
        """
        # De-dup against `blocked_routes`. The
        # `__contains__` check on a list is O(n) but
        # `n` is small (number of distinct routes
        # that ever got blocked) and the check keeps
        # the list semantically a "set of routes".
        if entry not in self._state.blocked_routes:
            self._state.blocked_routes.append(entry)
        # Always increment the per-call counter. Two
        # `mark_blocked` calls on the same route →
        # `blocked = 2`. The report cares about
        # block events, not distinct routes blocked.
        self._state.blocked += 1
        logger.info(
            "route_walker.blocked",
            path=entry.path,
            reason=reason,
            blocked_count=self._state.blocked,
        )

    def verdict(self) -> WalkerState:
        """Return a snapshot of the current `WalkerState`.

        The runner calls this at the end of the attack
        to capture coverage metrics for the report.
        The returned state is a *reference* to the
        walker's internal state — callers should treat
        it as read-only. Mutating it from outside
        corrupts the walker's accounting.
        """
        return self._state
