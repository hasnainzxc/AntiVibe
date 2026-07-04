"""Per-stack route mapper — builds route index with auth_required inference.

Architecture
------------
This module is the bridge between the scanner's static AST output
and the attack surface. It takes a `ParseResult` (routes found
by the parser) and enriches each route with:
    - `auth_required` — bool, inferred by reading the route file
      and looking for known auth-library import / call patterns.
    - normalized path — Next.js `[id]` and FastAPI `{id}` are
      converted to the canonical `:id` form.
    - `auth_stack` — the detected auth library, threaded through
      so downstream stages know which verifier to use.

The module never modifies the user's repo; it only reads source
files to do pattern matching.

Design rationale — substring detection vs. real AST
---------------------------------------------------
The `_has_auth_pattern` helper is a substring search, not a
full AST analysis. That's a deliberate trade-off:

    - Substring:    fast, robust to syntax variations, no language-
                    specific tooling required per stack. Misses
                    `import * as auth from 'next-auth'`-style
                    indirect imports (false negatives).
    - Full AST:     accurate but requires a per-stack tree-sitter
                    or babel pipeline, large dependency surface,
                    and a parser for each of the 6 stacks.

The substring approach is the right starting point. False
positives (route marked `auth_required=true` when it isn't) just
cause the scanner to attempt an authenticated probe where an
unauthenticated one would have worked — a recoverable miss.
False negatives (real auth not detected) are the bigger
problem, and the AUTH_PATTERNS dict can be expanded to add more
needle variants per stack. The `route.auth_required` fallback
in `build_route_index` lets a future AST-based detector override
the substring inference.

SENSITIVE_PATTERNS
------------------
A second heuristic marks routes whose path *suggests* they serve
sensitive data (`/api/users`, `/api/admin`, `/dashboard`, etc.).
The intersection — sensitive path *without* auth — is the
classic BOLA / broken-access-control signature. We log
`route_mapper.open_api_surface` at info level so the SOC can
see the open endpoints even when the attack stage doesn't
find a concrete exploit.

Dependency map
--------------
- Reads from: `scanner.ast_parser.ParseResult`, `RouteShape`,
              `parse_repo`.
- Writes to: nothing on disk; returns an in-memory list of
              `RouteIndexEntry`.
- Consumed by: the scanner's attack-surface enumeration stage.

Testing
-------
- `tests/sandbox/test_route_mapper.py` covers: each pattern
  category, the three path-normalization cases (Next.js,
  FastAPI, already-normalized), the sensitive-route
  classifier, and the full `build_route_index` integration
  with a synthetic AST.
"""

from dataclasses import dataclass, field
from pathlib import Path
from scanner.ast_parser import ParseResult, RouteShape, parse_repo
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RouteIndexEntry:
    """One enriched route in the index.

    `params` is a placeholder for future per-route param
    extraction (e.g. `{user_id: int}` from FastAPI path
    validators). Currently always empty; the field is
    reserved so the scanner can grow into it without a
    dataclass schema change.

    `auth_required` is a *best-effort* flag. See the module
    docstring for the substring-vs-AST trade-off.

    `auth_stack` records which library's patterns matched
    (or were checked against). Empty string when the AST
    didn't associate an auth library with the route.
    """

    path: str
    methods: list[str]
    params: dict = field(default_factory=dict)
    auth_required: bool = False
    auth_stack: str = ""
    file_path: str = ""
    line: int = 0


# Auth detection patterns per stack.
#
# Each entry is a *substring* that, if present in the route
# file's source, is strong evidence the route uses that auth
# library. Patterns are intentionally a mix of import statements
# and runtime call sites so both the declaration and the
# usage path are caught.
#
# Adding a new stack: add a key here, and add a `forge_*`
# adapter in `sandbox/jwt_forge.py` so the two registries
# stay in lockstep.
AUTH_PATTERNS = {
    "nextauth": [
        "getServerSession",
        "getSession",
        "NextAuth(",
        "authOptions",
        "import { auth } from",
        "import { getServerSession }",
    ],
    "clerk": [
        "auth()",
        "currentUser()",
        "import { auth } from '@clerk",
        "import { currentUser } from '@clerk",
        "authMiddleware",
    ],
    "firebase": [
        "onAuthStateChanged",
        "signInWithEmailAndPassword",
        "getAuth(",
        "requireAuth",
        "createSessionCookie",
    ],
    "supabase": [
        "supabase.auth.getUser()",
        "supabase.auth.getSession()",
        "createServerClient",
        "createClientComponentClient",
        "@supabase/ssr",
    ],
    "custom": [
        "JWT_SECRET",
        "jwt.sign(",
        "jwt.verify(",
        "jsonwebtoken",
        "verifyToken(",
        "authenticateToken",
        "authMiddleware",
        "requireAuth(",
    ],
}

# Route paths that *typically* serve sensitive data. Used as
# a signal (not a guarantee) — a route at `/api/users` is
# worth an unauthenticated probe even if the AST didn't
# find an auth pattern. The list is intentionally short and
# well-known; over-broadening it would generate noise.
#
# Matching is substring on the *normalized* path. `/api/users`
# will also match `/api/users/[id]`, which is the desired
# behavior (the dynamic path is the same resource).
SENSITIVE_PATTERNS = [
    "/api/users",
    "/api/admin",
    "/api/profile",
    "/api/account",
    "/api/data",
    "/api/projects",
    "/api/universities",
    "/api/documents",
    "/api/settings",
    "/admin",
    "/dashboard",
]


def _has_auth_pattern(file_content: str, auth_stack: str) -> bool:
    """Check if `file_content` contains auth patterns for `auth_stack`.

    Returns False (rather than raising) for an unknown
    `auth_stack` so a misconfigured caller doesn't blow up
    the entire route index build — it just gets a false-
    negative for routes under that stack.

    Args:
        file_content: Source text of the route file. Read
            with `errors="ignore"` upstream so binary or
            non-UTF-8 content does not crash the scan.
        auth_stack: Key into `AUTH_PATTERNS`. Unknown
            values return False.

    Returns:
        True iff at least one pattern for `auth_stack` is
        a substring of `file_content`.
    """
    patterns = AUTH_PATTERNS.get(auth_stack, [])
    for pattern in patterns:
        if pattern in file_content:
            return True
    return False


def _normalize_path(path: str) -> str:
    """Normalize route path placeholders to the `:param` convention.

    The scanner's downstream stages (fuzzing, path
    enumeration) operate on a single canonical syntax;
    this function bridges the per-framework conventions:

        Next.js:    `[id]`        → `:id`
        FastAPI:    `{item_id}`   → `:item_id`
        Express:    `:userId`     → already normalized
        SvelteKit:  `[slug]`      → `:slug`  (via Next.js rule)
        Flask:      `<int:id>`    → unchanged (intentionally;
                                    not yet supported; left as
                                    literal so fuzzer still
                                    reaches the route)

    Args:
        path: Raw path string from `RouteShape.path`.

    Returns:
        Path with `[name]` and `{name}` converted to `:name`.
        Already-normalized paths (containing `:name`) pass
        through unchanged.
    """
    import re  # Localized to keep module-level import surface small
    # Next.js and SvelteKit: `[param]` → `:param`. The `\[(\w+)\]`
    # pattern only matches square-bracket placeholders with a
    # single-word name (e.g. `[id]`, not `[a/b]` or `[...slug]`).
    # Catch-all routes (`[...slug]`) are not currently special-cased;
    # the substring still matches the prefix and the resulting
    # `:...slug` is benign for the fuzzer.
    path = re.sub(r'\[(\w+)\]', r':\1', path)
    # FastAPI: `{param}` → `:param`. Same word-only restriction.
    path = re.sub(r'\{(\w+)\}', r':\1', path)
    return path


def _is_sensitive_route(path: str) -> bool:
    """Check if `path` suggests it serves sensitive data.

    Substring match against `SENSITIVE_PATTERNS` *after*
    normalization. The normalization step matters:
    `/api/users/[id]` would *not* match `/api/users` as a
    raw substring check on the raw path, but it does match
    after the `[id]` → `:id` rewrite.

    Args:
        path: Path string (raw or already normalized; either
            works because the patterns are simple ASCII
            substrings).

    Returns:
        True if any `SENSITIVE_PATTERNS` substring is present.
    """
    normalized = _normalize_path(path)
    for pattern in SENSITIVE_PATTERNS:
        if pattern in normalized:
            return True
    return False


def build_route_index(ast_result: ParseResult, stack: str, auth_stack: str) -> list[RouteIndexEntry]:
    """Build a route index from AST parser results.

    For each route in `ast_result.routes`:
        1. Read the route file (if `route.file` is a real path).
        2. Set `auth_required` based on the substring match
           against `AUTH_PATTERNS[auth_stack]`.
        3. Fall back to `route.auth_required` (set by a future
           AST-based detector) if substring match was negative.
        4. Normalize the path.
        5. Emit a `RouteIndexEntry` with all the fields the
           scanner's downstream stages need.

    Args:
        ast_result: From `scanner.ast_parser.parse_repo()`.
            `ast_result.routes` is a `list[RouteShape]`.
        stack: Detected stack (`"nextjs"`, `"express"`, etc.).
            Currently informational only — passed through to
            the entry but not used in the inference logic.
            Kept in the signature so future stack-specific
            inference (e.g. Express middleware detection) has
            a place to branch.
        auth_stack: Detected auth library (`"nextauth"`,
            `"clerk"`, etc.). Drives the AUTH_PATTERNS lookup.

    Returns:
        List of `RouteIndexEntry`, one per input route, in the
        same order. Order preservation matters because the
        scanner correlates findings back to the original AST
        by index.

    Raises:
        Nothing under normal operation. File read errors
        (missing file, permission denied) are swallowed and
        leave the route's `auth_required` as False — a
        conservative default that biases the scanner toward
        probing (false positives are recoverable; false
        negatives hide vulns).
    """
    entries = []

    for route in ast_result.routes:
        # Defensive getattr chain. `RouteShape` is a dataclass
        # with these fields, but the `hasattr` guard makes this
        # tolerant of future schema changes (e.g. if `file`
        # becomes optional).
        file_path = Path(route.file) if hasattr(route, 'file') and route.file else None
        auth_required = False

        # Substring-based auth detection. The file read is
        # wrapped in a broad except because route files can
        # be in odd states (binary blobs the user named
        # `route.ts`, weird encodings, missing due to a
        # partial checkout). None of those are worth
        # aborting the index build for.
        if file_path and file_path.exists():
            try:
                content = file_path.read_text(errors="ignore")
                auth_required = _has_auth_pattern(content, auth_stack)
            except (OSError, UnicodeDecodeError):
                pass

        # AST-detected auth_required wins if substring found
        # nothing. This is the upgrade path for a future
        # tree-sitter based detector — it can set
        # `RouteShape.auth_required = True` and the substring
        # path will defer to it.
        if not auth_required and hasattr(route, 'auth_required'):
            auth_required = route.auth_required

        normalized_path = _normalize_path(route.path)
        # `methods` may be empty for routes where the parser
        # couldn't determine the HTTP verb (e.g. middleware
        # files that don't export named handlers). Default
        # to GET so the fuzzer at least pokes the URL.
        methods = route.methods if route.methods else ["GET"]
        # `line` and `file` are optional on RouteShape. The
        # entry always has the fields (dataclass), but
        # default to "" / 0 if the source is silent.
        line = route.line if hasattr(route, 'line') else 0
        fp = str(route.file) if hasattr(route, 'file') and route.file else ""

        entry = RouteIndexEntry(
            path=normalized_path,
            methods=methods,
            params={},
            auth_required=auth_required,
            auth_stack=auth_stack,
            file_path=fp,
            line=line,
        )
        entries.append(entry)

        # Open-API-surface signal: sensitive path with no
        # detected auth. Logged at info (not warning)
        # because this is a *signal* for the SOC, not an
        # error — the route may still be properly protected
        # by a middleware the substring detector missed.
        if not auth_required and _is_sensitive_route(normalized_path):
            logger.info(
                "route_mapper.open_api_surface",
                path=normalized_path,
                file=fp,
                auth_stack=auth_stack,
            )

    return entries


def build_index_from_repo(repo_path: str, stack: str, auth_stack: str = "custom") -> list[RouteIndexEntry]:
    """Convenience: parse the repo and build the index in one call.

    Wraps `parse_repo` + `build_route_index` for callers
    that don't already hold a `ParseResult` (e.g. the
    scan orchestrator's bootstrap path).

    Args:
        repo_path: Path to the cloned repo.
        stack: Detected stack string.
        auth_stack: Auth library string. Defaults to
            `"custom"` (i.e. "no specific library detected,
            fall back to substring matches against the
            custom/JSONWebToken pattern set").

    Returns:
        List of `RouteIndexEntry`.
    """
    ast_result = parse_repo(repo_path, stack)
    return build_route_index(ast_result, stack, auth_stack)
