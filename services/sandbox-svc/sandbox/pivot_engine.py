"""No-stop pivot engine for Tier 3 Fuzz Agent.

Architecture
------------
This module is the *control loop* of the Tier 3 fuzzer.
When a probe gets blocked (403 / 404 / 429), this engine
picks the next move: a different token, a different
method, a different path. It NEVER quits on a single
block — the fuzzer keeps pivoting until either a
finding lands (the runner reports a success) or the
per-probe attempt budget is exhausted.

Why a pivot engine, not a list of if-else
-----------------------------------------
The pivot rules are stateful: the *next* action
depends on which attempts have already been tried
for this probe. Encoding that as a state machine in
the engine makes the pivot history explicit and
testable. The alternative (a static lookup table
keyed by status) would force the runner to track
history itself, duplicating logic that's already in
the engine.

Per-probe attempt budget
------------------------
`max_tries` is the cap on how many pivot attempts a
single blocked probe can spawn before the engine
gives up. Default 4. The attempt counter is keyed
by the (path, method) of the ORIGINAL blocked probe
— pivots that change the path or method still count
toward the same budget, because they are attempts
on the same target. This bounds the worst-case
fan-out of the pivot strategy.

Why 5xx is a no-op
------------------
A 5xx response means the app is broken, not that
the probe was blocked. Pivoting on a 5xx would
waste attempts on an unreachable target. The runner
should log the 5xx and move on. The engine marks
the lineage exhausted on 5xx so the runner doesn't
re-prompt the engine with a stale 5xx.

429 — wait, then retry
----------------------
429 is a *soft* block: the server is rate-limiting,
not rejecting. The right move is to wait the
`Retry-After` (when present) and re-fire the same
probe. The engine surfaces the delay via
`PivotAction.action == "retry_with_patch"` — the
runner is responsible for the actual sleep.

Dependency map
--------------
- Reads from: `sandbox.route_walker.CurlProbe`,
              `sandbox.route_walker.WalkerState`.
- Consumed by: the Tier 3 orchestrator (Task 29).
- Emits: `PivotAction` records that the runner turns
         into the next HTTP request.

Testing
-------
- `tests/sandbox/test_pivot_engine.py` covers: 403
  token swap, 404 adjacent path, 429 retry, 5xx
  skip, max_tries=4 cap. No real HTTP — responses
  are constructed via `httpx.Response(...)` and
  never sent.
"""

from dataclasses import dataclass
from typing import Any, Literal

import structlog

from sandbox.route_walker import CurlProbe, WalkerState

logger = structlog.get_logger(__name__)


# Action tag set. Mirrors the strategy table below.
# Kept as a tuple-of-strings (not an Enum) so the
# value is JSON-serialisable in the audit log without
# a custom encoder. The Literal type on `PivotAction`
# is the source of truth for the runtime check.
PIVOT_ACTIONS = (
    "retry_with_patch",
    "method_swap",
    "token_swap",
    "adjacent_path",
    "param_extension",
)


# HTTP method mapping for the "method swap" pivot.
# When a GET 403s, the first method-swap attempt
# uses the first entry in this list that is not the
# probe's current method. The order picks the most
# likely-to-be-writable verbs first: POST (create)
# before PUT (replace) before PATCH (partial) before
# DELETE. Real-world APIs tend to gate writes on a
# different verb than reads.
_METHOD_SWAP_ORDER = ("POST", "PUT", "PATCH", "DELETE")


# Param extension suffixes for the 404 pivot.
# These append a sub-resource to the original path:
# `/api/users/123` -> `/api/users/123/settings`. The
# list is ordered by what real-world APIs tend to
# expose on a `/:id`-style resource: per-user
# settings, then admin-only sub-resources, then
# billing. The first element is the default; later
# ones can be reached by cycling through the
# 2-action sequence across attempts.
_PARAM_EXTENSION_SUFFIXES = ("/settings", "/admin", "/billing")


# Per-status pivot strategy. Maps the block status
# code to the ordered sequence of actions to attempt.
# The engine walks this sequence in order, rotating
# back to the start when attempts exceed the
# sequence length (so max_tries=4 still produces 4
# actions for a 2-element sequence).
_PIVOT_SEQUENCE: dict[int, tuple[str, ...]] = {
    403: ("token_swap", "method_swap"),
    404: ("adjacent_path", "param_extension"),
}


# Default fallback when no `max_tries` is given.
DEFAULT_MAX_TRIES = 4


@dataclass
class PivotAction:
    """One pivot step the runner should execute next.

    Fields:
        action:     One of PIVOT_ACTIONS. The runner
                    dispatches on this tag to decide
                    what to do.
        probe:      The next `CurlProbe` to fire.
                    May be identical to the blocked
                    probe (for 429 retries) or
                    materially different (for 403 /
                    404 pivots).
        attempt:    1-based attempt number for the
                    original blocked probe's pivot
                    lineage. The first pivot is
                    attempt 1; the engine returns
                    None once `attempt > max_tries`.
        max_tries:  The attempt cap. Surfaced on the
                    action so the runner can include
                    it in the log line without
                    re-reading the engine's config.
    """

    action: Literal[
        "retry_with_patch",
        "method_swap",
        "token_swap",
        "adjacent_path",
        "param_extension",
    ]
    probe: CurlProbe
    attempt: int
    max_tries: int = DEFAULT_MAX_TRIES


def _response_status(response: Any) -> int:
    """Extract the status code from a response object.

    Accepts `httpx.Response` (duck-typed via
    `.status_code`), a dict with a `"status"` key, or
    a raw int. Returns 0 for None or unknown shapes —
    0 is the same sentinel used by `bola_tester` for
    network errors and is treated as "no signal" by
    the pivot engine.
    """
    if response is None:
        return 0
    if isinstance(response, int):
        return response
    if hasattr(response, "status_code"):
        try:
            return int(response.status_code)
        except (TypeError, ValueError):
            return 0
    if isinstance(response, dict):
        value = response.get("status")
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0


def _response_retry_after(response: Any) -> float:
    """Extract the Retry-After delay from a response.

    Accepts `httpx.Response` (via `.headers`) or a
    dict with a `"headers"` key. Header lookup is
    case-insensitive. Returns 0.0 when the header is
    absent, unparseable, or the response is unknown.
    The runner uses this delay to schedule the
    retry; a 0.0 result means "retry immediately,
    the server didn't tell us to wait".
    """
    if response is None:
        return 0.0
    headers: Any = None
    if hasattr(response, "headers"):
        headers = response.headers
    elif isinstance(response, dict):
        headers = response.get("headers")

    if headers is None:
        return 0.0

    # httpx.Headers is case-insensitive on lookup;
    # a raw dict may not be. Try both casings.
    raw: Any = None
    try:
        raw = headers.get("Retry-After")
    except (AttributeError, TypeError):
        raw = None
    if raw is None:
        try:
            raw = headers.get("retry-after")
        except (AttributeError, TypeError):
            raw = None

    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _parent_path(path: str) -> str:
    """Strip the last path segment, returning the parent.

    `/api/users/123` -> `/api/users`
    `/api/users`     -> `/api`
    `/api`           -> `/` (root is its own parent)
    `users`          -> `/` (no slash -> treat as root)
    `""`             -> `/` (defensive: empty path)
    """
    stripped = path.rstrip("/")
    if not stripped:
        return "/"
    if "/" not in stripped:
        return "/"
    parent = stripped.rsplit("/", 1)[0]
    if not parent:
        return "/"
    return parent


def _new_probe_like(
    base: CurlProbe,
    method: str | None = None,
    path: str | None = None,
    token_type: str | None = None,
) -> CurlProbe:
    """Build a new CurlProbe from a base probe with overrides.

    A copy-and-mutate helper. `headers` is shallow-
    copied so the original probe is not mutated when
    the pivot action rebuilds Authorization headers.
    Fields not overridden keep their base value.
    """
    return CurlProbe(
        method=method if method is not None else base.method,
        path=path if path is not None else base.path,
        headers=dict(base.headers),
        body=base.body,
        token_type=token_type if token_type is not None else base.token_type,
        route_entry=base.route_entry,
    )


class PivotEngine:
    """Stateful pivot planner for blocked probes.

    Tracks per-probe attempt counts so the engine can
    decide what to do next time the runner calls
    `pivot()` for the same probe. The state is keyed
    by (path, method) of the ORIGINAL blocked probe —
    pivots that change the path or method still
    count toward the same budget, because they are
    attempts on the same target.

    The engine is intentionally cheap to construct:
    no I/O, no logging side-effects beyond debug
    calls. The runner owns one PivotEngine per scan
    and calls `pivot()` once per blocked probe.

    Args:
        max_tries:   Cap on pivot attempts per probe
                     lineage. Default 4. The first
                     pivot is attempt 1; the engine
                     returns None at attempt ==
                     max_tries. Must be >= 1.
    """

    def __init__(self, max_tries: int = DEFAULT_MAX_TRIES):
        if max_tries < 1:
            raise ValueError("max_tries must be >= 1")
        self.max_tries = max_tries
        # (path, method) -> attempt count. The key
        # uses the ORIGINAL probe's (path, method);
        # pivots that change either field still
        # resolve to the same key, so the attempt
        # budget is per-original-target.
        self._attempts: dict[tuple[str, str], int] = {}
        # (path, method) -> True once the engine has
        # given up on that lineage. Distinct from
        # `_attempts[key] > max_tries` because 5xx
        # exhausts the lineage WITHOUT incrementing
        # the attempt counter (we don't want a
        # later 403 to inherit a 5xx's budget burn).
        self._exhausted: set[tuple[str, str]] = set()

    @staticmethod
    def _lineage_key(probe: CurlProbe) -> tuple[str, str]:
        """Compute the lineage key for a probe.

        The lineage key is the (path, method) of the
        probe. All pivots spawned from a probe with
        the same (path, method) share the lineage
        key, so the attempt budget is enforced per
        original target.
        """
        return (probe.path, probe.method)

    def _bump_attempt(self, key: tuple[str, str]) -> int:
        """Increment the attempt counter for `key`.

        Returns the new (post-increment) attempt
        number. 1-based: the first call returns 1.
        """
        next_count = self._attempts.get(key, 0) + 1
        self._attempts[key] = next_count
        return next_count

    def is_exhausted(self, probe: CurlProbe) -> bool:
        """Return True when the probe's lineage is exhausted.

        Public helper. The runner uses this to short-
        circuit before calling `pivot()` again on a
        probe that was already given up on (e.g. via
        a 5xx).
        """
        return self._lineage_key(probe) in self._exhausted

    @staticmethod
    def _build_token_swap(probe: CurlProbe) -> CurlProbe:
        """Return a probe with the token variant flipped.

        Heuristic: the original probe carries one of
        `"user_a"`, `"user_b"`, or `"none"` in its
        `token_type`. We swap a <-> b; for the
        tokenless case we fall back to `user_a`
        (the most generic cross-tenant probe).

        The actual `Authorization` header is NOT
        rebuilt here — the runner owns the token
        pool and re-derives the header from
        `probe.token_type` when it dispatches. The
        engine only signals which token variant to
        use.
        """
        if probe.token_type == "user_a":
            new_token = "user_b"
        elif probe.token_type == "user_b":
            new_token = "user_a"
        else:
            new_token = "user_a"
        return _new_probe_like(probe, token_type=new_token)

    @staticmethod
    def _build_method_swap(probe: CurlProbe) -> CurlProbe:
        """Return a probe with the HTTP method swapped.

        The first non-current method in
        `_METHOD_SWAP_ORDER` is used. This is
        deterministic per probe: a GET always
        pivots to POST, a POST always pivots to PUT,
        and so on. Test reproducibility depends on
        this stability.
        """
        new_method = next(
            (m for m in _METHOD_SWAP_ORDER if m != probe.method),
            "POST",
        )
        return _new_probe_like(probe, method=new_method)

    @staticmethod
    def _build_adjacent_path(probe: CurlProbe) -> CurlProbe:
        """Return a probe with PATCH on the parent path.

        For `/api/users/123`, the parent is
        `/api/users`. The method is forced to
        PATCH — a 404 on a GET suggests the
        collection endpoint may accept writes even
        when the item endpoint does not.
        """
        return _new_probe_like(
            probe,
            method="PATCH",
            path=_parent_path(probe.path),
        )

    @staticmethod
    def _build_param_extension(probe: CurlProbe) -> CurlProbe:
        """Return a probe with a sub-resource appended.

        `/api/users/123` -> `/api/users/123/settings`.
        The first suffix in
        `_PARAM_EXTENSION_SUFFIXES` is used; later
        attempts can rotate through the rest by
        cycling the action sequence.
        """
        suffix = _PARAM_EXTENSION_SUFFIXES[0]
        new_path = probe.path.rstrip("/") + suffix
        return _new_probe_like(probe, path=new_path)

    async def pivot(
        self,
        blocked_probe: CurlProbe,
        walker_verdict: WalkerState,
        observed_responses: list,
    ) -> PivotAction | None:
        """Decide the next pivot action for a blocked probe.

        Reads the most recent response status and
        walks the per-status pivot sequence. Each
        call advances the attempt counter; once the
        counter reaches `max_tries`, the engine
        marks the lineage exhausted and returns
        None.

        Decision tree:

            5xx     -> return None (app broken,
                       not blocked). Marks the
                       lineage exhausted so the
                       runner doesn't re-prompt.
            429     -> return retry_with_patch with
                       the same probe. The runner
                       is expected to wait the
                       Retry-After delay before
                       re-firing.
            403     -> walk (token_swap,
                       method_swap) sequence.
            404     -> walk (adjacent_path,
                       param_extension) sequence.
            other   -> return None (no strategy).

        Args:
            blocked_probe:        The probe that was
                                  blocked. The
                                  engine uses
                                  `path` /
                                  `method` /
                                  `token_type` /
                                  `headers` /
                                  `body` /
                                  `route_entry` to
                                  build the next
                                  probe.
            walker_verdict:       The current
                                  `WalkerState` from
                                  the route walker.
                                  Logged for
                                  observability;
                                  the engine does
                                  not mutate walker
                                  state.
            observed_responses:   List of recent
                                  responses. The
                                  engine uses the
                                  LAST entry's
                                  status to drive
                                  the pivot
                                  decision and, for
                                  429, its
                                  `Retry-After`
                                  header for the
                                  delay.

        Returns:
            `PivotAction` describing the next probe
            to fire, or `None` when the lineage is
            exhausted or the status is not in the
            strategy table.
        """
        key = self._lineage_key(blocked_probe)

        # Already exhausted (e.g. a previous 5xx on
        # the same lineage). Return None without
        # touching the attempt counter — the
        # engine has already given up on this one.
        if key in self._exhausted:
            return None

        # Resolve the most recent response status.
        # We accept any iterable but expect list-like
        # ordering. A non-list input is treated as
        # empty (status 0 -> no strategy).
        if not isinstance(observed_responses, list):
            status = 0
            last_response: Any = None
        else:
            last_response = observed_responses[-1] if observed_responses else None
            status = _response_status(last_response)

        # 5xx: app broken, not blocked. Mark
        # exhausted and return None. We do NOT
        # increment the attempt counter here — a
        # 5xx is a signal, not a pivot attempt.
        if 500 <= status < 600:
            self._exhausted.add(key)
            logger.info(
                "pivot_engine.skip_5xx",
                path=blocked_probe.path,
                method=blocked_probe.method,
                status=status,
                walker_visited=walker_verdict.visited,
            )
            return None

        # 429: rate-limited. Re-fire the same
        # probe. The runner reads the action and
        # schedules a wait based on the Retry-After
        # header (parsed below into the
        # PivotAction's max_tries-or-attempt
        # surface; the runner pulls the raw
        # response to read the header again).
        if status == 429:
            attempt = self._bump_attempt(key)
            if attempt > self.max_tries:
                self._exhausted.add(key)
                logger.info(
                    "pivot_engine.exhausted",
                    path=blocked_probe.path,
                    method=blocked_probe.method,
                    attempt=attempt,
                )
                return None
            delay = _response_retry_after(last_response)
            logger.info(
                "pivot_engine.retry_429",
                path=blocked_probe.path,
                attempt=attempt,
                delay=delay,
            )
            return PivotAction(
                action="retry_with_patch",
                probe=blocked_probe,
                attempt=attempt,
                max_tries=self.max_tries,
            )

        # 403 / 404: walk the per-status pivot
        # sequence. Other statuses (401, 400, 2xx,
        # 3xx) have no pivot strategy — return
        # None and exhaust the lineage so the runner
        # doesn't loop on them.
        sequence = _PIVOT_SEQUENCE.get(status)
        if sequence is None:
            self._exhausted.add(key)
            logger.info(
                "pivot_engine.no_strategy",
                path=blocked_probe.path,
                method=blocked_probe.method,
                status=status,
            )
            return None

        attempt = self._bump_attempt(key)
        if attempt > self.max_tries:
            self._exhausted.add(key)
            logger.info(
                "pivot_engine.exhausted",
                path=blocked_probe.path,
                method=blocked_probe.method,
                attempt=attempt,
            )
            return None

        # Pick the action for this attempt. We
        # rotate through the sequence so a 2-element
        # sequence still produces 4 actions when
        # max_tries=4: attempts 1-2 walk the
        # sequence in order, attempts 3-4 wrap
        # back. The action tag tells the runner
        # what shape of probe to expect; the
        # attempt counter is the budget the runner
        # displays in the audit log.
        action_index = (attempt - 1) % len(sequence)
        action = sequence[action_index]

        builders = {
            "token_swap": self._build_token_swap,
            "method_swap": self._build_method_swap,
            "adjacent_path": self._build_adjacent_path,
            "param_extension": self._build_param_extension,
        }
        builder = builders.get(action)
        if builder is None:
            # Defensive: the sequence is closed
            # over the action-tag set, so this
            # branch should be unreachable. Mark
            # exhausted and bail.
            self._exhausted.add(key)
            return None

        new_probe = builder(blocked_probe)
        logger.info(
            "pivot_engine.action",
            path=blocked_probe.path,
            method=blocked_probe.method,
            action=action,
            attempt=attempt,
            new_path=new_probe.path,
            new_method=new_probe.method,
        )
        return PivotAction(
            action=action,
            probe=new_probe,
            attempt=attempt,
            max_tries=self.max_tries,
        )
