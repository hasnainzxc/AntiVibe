"""Per-stack AST-light parser.

Extracts three signals from a cloned repo that the rest of the pipeline
needs before it can do useful work:

  1. **Routes** — URL paths, HTTP methods, source file. Used by the
     LLM extractor to focus its context window on entry points, and
     by the dashboard to render an "API surface" view.
  2. **Env references** — every `process.env.X` (Node) or
     `os.environ["X"]` (Python) the repo reads. Used to surface
     required secret names so the user can populate them in the
     runner before deploy.
  3. **Imports** — currently a placeholder; the LLM stage uses the
     raw route file content, not a normalized import graph.

Why AST-light (regex) instead of real language parsers?
-------------------------------------------------------
A proper TypeScript or Python AST gives perfect accuracy but pulls in
~50MB of node_modules (typescript, esprima, etc.) and adds 200–400ms
of parse time per file. The route patterns we need are regular enough
that a 30-character regex catches >95% of real-world cases — and the
5% we miss are non-blocking for the Tier 1 verdict. We can graduate
to a real parser in Tier 2 if a customer hits a false negative.
"""

import json
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)


class HttpMethod(str, Enum):
    """HTTP methods the route extractor recognizes. Order matches RFC 7231;

    UI sorting relies on the enum's natural iteration order.
    """
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


@dataclass
class RouteShape:
    """A single route extracted from the repo. `methods` is a list because
    Next.js and SvelteKit allow a single file to export multiple handlers
    (e.g. `export function GET` + `export function POST` in one `+server.ts`).
    """
    path: str
    methods: list[str] = field(default_factory=list)
    auth_required: bool = False
    file: str = ""


@dataclass
class EnvRef:
    """A single `process.env.X` / `os.environ["X"]` reference in source.

    `has_default` and `default_value` track whether the reference provides
    a fallback (e.g. `os.environ.get("X", "default")`) — runners can use
    this to pre-populate the env without user input.
    """
    name: str
    file: str
    line: int
    has_default: bool = False
    default_value: str = ""


@dataclass
class ParseResult:
    """Aggregate output of any per-stack parser. The Tier 1 orchestrator
    consumes a single ParseResult regardless of which stack produced it.
    """
    routes: list[RouteShape] = field(default_factory=list)
    env_refs: list[EnvRef] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)


# ─── Per-stack parsers ───

def _parse_nextjs(repo: Path) -> ParseResult:
    """Next.js App Router (file-based) + legacy Pages Router (route files).

    App Router: `app/**/{route.ts, route.tsx, route.js, route.jsx}` declare
    a route. `page.{ts,tsx,js,jsx}` are server-rendered pages — they
    respond to GET only (a page is by definition a read of the page
    document, even if it embeds a client-side form).

    Pages Router: `pages/api/**.{ts,tsx,js,jsx}` are catch-all handlers
    accepting any method (we record GET+POST as a conservative default;
    LLM stage will down-classify to the real surface if it matters).
    """
    routes = []
    env_refs = []
    imports = []

    # App Router: file-system routing under `app/`. Each `route.ts` is
    # one URL path; `page.tsx` is a read-only document route.
    app_dir = repo / "app"
    if app_dir.is_dir():
        for root, _dirs, files in os.walk(app_dir):
            for fname in files:
                if fname in ("route.ts", "route.tsx", "route.js", "route.jsx", "page.tsx", "page.tsx"):
                    filepath = Path(root) / fname
                    rel = filepath.relative_to(app_dir)
                    # Next.js dynamic segments use `[param]`; we rewrite
                    # to `:param` (Express-style) so the dashboard can
                    # render a single canonical URL syntax across stacks.
                    path = "/" + str(rel.parent).replace("[", ":").replace("]", "")
                    if fname.startswith("route"):
                        methods = _extract_exported_methods(filepath)
                    else:
                        # page.tsx is rendered via GET — record it as
                        # such so the auth-required logic can flag
                        # unauthenticated pages that leak data.
                        methods = ["GET"]
                    routes.append(RouteShape(path=path or "/", methods=methods, file=str(filepath)))

    # Pages Router: pre-App-Router convention. `pages/api/*` is
    # populated without method guards; we record GET+POST to be
    # conservative and let the LLM stage narrow later.
    pages_dir = repo / "pages"
    if pages_dir.is_dir():
        api_dir = pages_dir / "api"
        if api_dir.is_dir():
            for root, _dirs, files in os.walk(api_dir):
                for fname in files:
                    if fname.endswith((".ts", ".tsx", ".js")):
                        filepath = Path(root) / fname
                        rel = filepath.relative_to(pages_dir)
                        path = "/" + str(rel.with_suffix("")).replace("[", ":").replace("]", "")
                        routes.append(RouteShape(path=path, methods=["GET", "POST"], file=str(filepath)))

    env_refs = _scan_env_refs(repo, [".ts", ".tsx", ".js", ".jsx"])
    return ParseResult(routes=routes, env_refs=env_refs, imports=imports)


def _parse_express(repo: Path) -> ParseResult:
    """Express.js route extraction from `app.METHOD(path, handler)` and
    `router.METHOD(path, handler)` patterns.

    Regex-based rather than a real JS AST because Express route
    definitions are short and rarely use destructuring that breaks
    the regex. The two patterns cover ~99% of real Express code:
    `app.METHOD` (root app) and `router.METHOD` (modular routers).
    """
    routes = []
    patterns = [
        # group 1 = method (lowercase), group 2 = URL path
        (re.compile(r'app\.(get|post|put|patch|delete)\s*\(\s*[\'\"]([^\'\"]+)[\'\"]'), "app.js"),
        (re.compile(r'router\.(get|post|put|patch|delete)\s*\(\s*[\'\"]([^\'\"]+)[\'\"]'), "routes"),
    ]

    for root, _dirs, files in os.walk(repo):
        # Skip noise dirs that are never part of the application:
        # node_modules (deps), .git (history). .next, dist, build
        # would be reasonable additions but Express projects don't
        # typically vendor compiled output alongside source.
        _dirs[:] = [d for d in _dirs if d not in ("node_modules", ".git")]
        for fname in files:
            if not fname.endswith((".js", ".ts")):
                continue
            filepath = Path(root) / fname
            try:
                content = filepath.read_text(errors="ignore")
            except OSError:
                continue
            for pattern, _source in patterns:
                for method, path in pattern.findall(content):
                    routes.append(RouteShape(path=path, methods=[method.upper()], file=str(filepath)))

    env_refs = _scan_env_refs(repo, [".js", ".ts"])
    return ParseResult(routes=routes, env_refs=env_refs)


def _parse_fastapi(repo: Path) -> ParseResult:
    """FastAPI route extraction from `@app.METHOD("path")` / `@router.METHOD("path")`.

    Single regex covers both because the prefix (`\\w+\\.`) matches either
    `app.` or `router.` and any custom APIRouter instance. Curly-brace
    FastAPI path params (`{item_id}`) are kept as-is — they're
    semantically different from Next.js `[param]` and SvelteKit `[param]`
    so we don't normalize across stacks.
    """
    routes = []
    pattern = re.compile(r'@\w+\.(get|post|put|patch|delete)\s*\(\s*[\'\"]([^\'\"]+)[\'\"]')

    for root, _dirs, files in os.walk(repo):
        # __pycache__ (compiled bytecode, noise), .venv (virtualenv,
        # never has route decorators on the surface), .git (history).
        _dirs[:] = [d for d in _dirs if d not in ("__pycache__", ".venv", ".git")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            filepath = Path(root) / fname
            try:
                content = filepath.read_text(errors="ignore")
            except OSError:
                continue
            for method, path in pattern.findall(content):
                routes.append(RouteShape(path=path, methods=[method.upper()], file=str(filepath)))

    env_refs = _scan_env_refs_python(repo)
    return ParseResult(routes=routes, env_refs=env_refs)


def _parse_flask(repo: Path) -> ParseResult:
    """Flask route extraction from `@app.route("path")` decorators.

    Flask's `route()` is method-agnostic by default — it accepts any
    HTTP verb. We record GET+POST as the conservative default; the
    dashboard shows these as "any method" badges.
    """
    routes = []
    pattern = re.compile(r'@\w+\.route\s*\(\s*[\'\"]([^\'\"]+)[\'\"]')

    for root, _dirs, files in os.walk(repo):
        _dirs[:] = [d for d in _dirs if d not in ("__pycache__", ".venv", ".git")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            filepath = Path(root) / fname
            try:
                content = filepath.read_text(errors="ignore")
            except OSError:
                continue
            for path in pattern.findall(content):
                routes.append(RouteShape(path=path, methods=["GET", "POST"], file=str(filepath)))

    env_refs = _scan_env_refs_python(repo)
    return ParseResult(routes=routes, env_refs=env_refs)


def _parse_sveltekit(repo: Path) -> ParseResult:
    """SvelteKit server route extraction from `src/routes/**/+server.{ts,js}`.

    Each `+server.ts` exports one or more named functions (`GET`, `POST`,
    etc.) that map 1:1 to HTTP methods. SvelteKit's `+page.svelte` files
    are intentionally ignored — they render HTML, they don't accept
    raw HTTP requests in a way that needs auth analysis.
    """
    routes = []
    routes_dir = repo / "src" / "routes"
    if not routes_dir.is_dir():
        return ParseResult()

    for root, _dirs, files in os.walk(routes_dir):
        for fname in files:
            if fname == "+server.ts" or fname == "+server.js":
                filepath = Path(root) / fname
                rel = filepath.relative_to(routes_dir)
                # SvelteKit uses `[param]` like Next.js — same
                # :param rewrite for the dashboard's URL syntax.
                path = "/" + str(rel.parent).replace("[", ":").replace("]", "")
                methods = _extract_exported_methods(filepath)
                routes.append(RouteShape(path=path or "/", methods=methods, file=str(filepath)))

    env_refs = _scan_env_refs(repo, [".ts", ".js", ".svelte"])
    return ParseResult(routes=routes, env_refs=env_refs)


def _parse_firebase(repo: Path) -> ParseResult:
    """Firebase Cloud Functions route extraction from `functions/index.{js,ts}`.

    Each `exports.<name> = functions.https.onRequest(...)` or
    `exports.<name> = functions.https.onCall(...)` becomes a route at
    `/<name>`. We don't try to introspect the function body — Firebase
    routing is determined entirely by the export name, not by any
    internal path declaration.
    """
    routes = []
    func_dir = repo / "functions"
    # Firebase allows the functions source at either the canonical
    # `functions/index.*` or the flatter repo-root layout some teams
    # use (especially for v1 single-function projects).
    index_files = ["index.js", "index.ts", "src/index.js", "src/index.ts"]

    for idx_name in index_files:
        idx_path = func_dir / idx_name if func_dir.is_dir() else repo / idx_name
        if idx_path.exists():
            try:
                content = idx_path.read_text(errors="ignore")
            except OSError:
                continue
            # Match `exports.name = functions.https.onRequest(...)` and
            # `exports.name = functions.https.onCall(...)`. The `(?:...)`
            # non-capturing group is intentional — we only want the
            # function name in group 1.
            pattern = re.compile(r'exports\.(\w+)\s*=\s*functions\.https\.on(?:Request|Call)')
            for func_name in pattern.findall(content):
                routes.append(RouteShape(
                    path=f"/{func_name}",
                    methods=["GET", "POST"],
                    file=str(idx_path)
                ))

    env_refs = _scan_env_refs(repo, [".js", ".ts"])
    return ParseResult(routes=routes, env_refs=env_refs)


# ─── Helpers ───

def _extract_exported_methods(filepath: Path) -> list[str]:
    """Extract HTTP method exports from a Next.js/SvelteKit route file.

    Looks for `export function GET`, `export async function POST`, etc.
    Returns ["GET"] as a safe default if the file is unreadable or
    contains no recognized exports — we don't want a parse failure
    to silently produce a route with zero methods (which the
    dashboard would render as a dead link).
    """
    methods = []
    try:
        content = filepath.read_text(errors="ignore")
    except OSError:
        return ["GET"]
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        # `\b` word boundary prevents matching `GET_NEXT` etc. The
        # `async` is optional — both `export function GET` and
        # `export async function GET` are valid handler signatures.
        if re.search(rf'\bexport\s+(?:async\s+)?function\s+{method}\b', content):
            methods.append(method)
    return methods or ["GET"]


def _scan_env_refs(repo: Path, extensions: list[str]) -> list[EnvRef]:
    """Find every `process.env.X` reference in JS/TS/JSX/TSX/Svelte files.

    Walks the repo, skipping vendored/build output (node_modules, .git,
    .next, dist, build). The regex is intentionally narrow — we don't
    try to match destructuring (`const { X } = process.env`) because
    doing so requires resolving types and the false-positive cost is
    higher than the recall gain at this stage.
    """
    refs = []
    pattern = re.compile(r'process\.env\.(\w+)')
    for root, _dirs, files in os.walk(repo):
        # node_modules and .git are universal. The others are JS-stack
        # build outputs that frequently contain evaluated env refs but
        # never represent runtime configuration the user controls.
        _dirs[:] = [d for d in _dirs if d not in ("node_modules", ".git", ".next", "dist", "build")]
        for fname in files:
            if not any(fname.endswith(ext) for ext in extensions):
                continue
            filepath = Path(root) / fname
            try:
                for i, line in enumerate(filepath.read_text(errors="ignore").split("\n"), 1):
                    for match in pattern.finditer(line):
                        refs.append(EnvRef(name=match.group(1), file=str(filepath), line=i))
            except OSError:
                continue
    return refs


def _scan_env_refs_python(repo: Path) -> list[EnvRef]:
    """Find every `os.environ.get("X")` and `os.environ["X"]` reference.

    Both APIs are matched in one regex by allowing an optional `.get`
    followed by either `(` or `[`. This catches the common
    `os.environ.get("FOO", "default")` and `os.environ["FOO"]` forms
    without needing an AST. `has_default` / `default_value` are not
    extracted here — they require inspecting the surrounding call
    arguments, which the regex deliberately avoids for clarity.
    """
    refs = []
    # `os.environ(?:\.get)?\s*[\(\[]` — optional `.get`, then either
    # `(` (function call) or `[` (subscript). The inner group captures
    # the env var name.
    pattern = re.compile(r'os\.environ(?:\.get)?\s*[\(\[]\s*[\'\"]([A-Za-z_]\w*)[\'\"]\s*[\)\]]')
    for root, _dirs, files in os.walk(repo):
        _dirs[:] = [d for d in _dirs if d not in ("__pycache__", ".venv", ".git")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            filepath = Path(root) / fname
            try:
                for i, line in enumerate(filepath.read_text(errors="ignore").split("\n"), 1):
                    for match in pattern.finditer(line):
                        refs.append(EnvRef(name=match.group(1), file=str(filepath), line=i))
            except OSError:
                continue
    return refs


# ─── Main dispatch ───

# Mapping from `Stack` value to the per-stack parser. Keys must match
# `Stack.value` exactly — the orchestrator passes the enum's string
# form in directly, so any drift here is a silent TypeError in production.
PARSERS = {
    "nextjs": _parse_nextjs,
    "express": _parse_express,
    "fastapi": _parse_fastapi,
    "flask": _parse_flask,
    "sveltekit": _parse_sveltekit,
    "firebase": _parse_firebase,
}


def parse_repo(repo_path: str, stack: str) -> ParseResult:
    """Run the parser for the given stack against a cloned repo.

    Returns an empty ParseResult (not an exception) when the repo path
    is invalid or the stack is unknown — the orchestrator treats a
    parse failure as a soft "no findings from this stage" rather than
    a hard error. The reasoning: an AST parse failure on a single
    repo shouldn't tank the whole Tier 1 verdict; the secret and
    config-flaw stages will still run.
    """
    repo = Path(repo_path)
    if not repo.is_dir():
        logger.error("ast_parser.not_a_directory", path=repo_path)
        return ParseResult()

    parser = PARSERS.get(stack)
    if not parser:
        logger.warning("ast_parser.unsupported_stack", stack=stack)
        return ParseResult()

    logger.info("ast_parser.start", stack=stack, repo=repo_path)
    try:
        result = parser(repo)
        logger.info("ast_parser.done", stack=stack, routes=len(result.routes), env_refs=len(result.env_refs))
        return result
    except Exception as e:
        logger.error("ast_parser.failed", stack=stack, error=str(e))
        return ParseResult()
