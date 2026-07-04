"""AST parser per stack — extracts routes, env refs, imports."""

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
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"

@dataclass
class RouteShape:
    path: str
    methods: list[str] = field(default_factory=list)
    auth_required: bool = False
    file: str = ""

@dataclass
class EnvRef:
    name: str
    file: str
    line: int
    has_default: bool = False
    default_value: str = ""

@dataclass
class ParseResult:
    routes: list[RouteShape] = field(default_factory=list)
    env_refs: list[EnvRef] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)

# ─── Per-stack parsers ───

def _parse_nextjs(repo: Path) -> ParseResult:
    """Next.js App Router + Pages Router route extraction."""
    routes = []
    env_refs = []
    imports = []

    # App Router: app/**/{route.ts, page.tsx}
    app_dir = repo / "app"
    if app_dir.is_dir():
        for root, _dirs, files in os.walk(app_dir):
            for fname in files:
                if fname in ("route.ts", "route.tsx", "route.js", "route.jsx", "page.tsx", "page.tsx"):
                    filepath = Path(root) / fname
                    rel = filepath.relative_to(app_dir)
                    # Convert [param] to :param
                    path = "/" + str(rel.parent).replace("[", ":").replace("]", "")
                    if fname.startswith("route"):
                        methods = _extract_exported_methods(filepath)
                    else:
                        methods = ["GET"]  # page.tsx = GET only
                    routes.append(RouteShape(path=path or "/", methods=methods, file=str(filepath)))

    # Pages Router: pages/api/**.ts
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
    """Express.js route extraction from app.js and routes/ directory."""
    routes = []
    # Scan for app.METHOD(path, handler) patterns
    patterns = [
        (re.compile(r'app\.(get|post|put|patch|delete)\s*\(\s*[\'\"]([^\'\"]+)[\'\"]'), "app.js"),
        (re.compile(r'router\.(get|post|put|patch|delete)\s*\(\s*[\'\"]([^\'\"]+)[\'\"]'), "routes"),
    ]

    for root, _dirs, files in os.walk(repo):
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
    """FastAPI route extraction from decorators."""
    routes = []
    pattern = re.compile(r'@\w+\.(get|post|put|patch|delete)\s*\(\s*[\'\"]([^\'\"]+)[\'\"]')

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
            for method, path in pattern.findall(content):
                routes.append(RouteShape(path=path, methods=[method.upper()], file=str(filepath)))

    env_refs = _scan_env_refs_python(repo)
    return ParseResult(routes=routes, env_refs=env_refs)


def _parse_flask(repo: Path) -> ParseResult:
    """Flask route extraction from @app.route decorators."""
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
    """SvelteKit route extraction from src/routes/**/+server.ts exports."""
    routes = []
    routes_dir = repo / "src" / "routes"
    if not routes_dir.is_dir():
        return ParseResult()

    for root, _dirs, files in os.walk(routes_dir):
        for fname in files:
            if fname == "+server.ts" or fname == "+server.js":
                filepath = Path(root) / fname
                rel = filepath.relative_to(routes_dir)
                path = "/" + str(rel.parent).replace("[", ":").replace("]", "")
                methods = _extract_exported_methods(filepath)
                routes.append(RouteShape(path=path or "/", methods=methods, file=str(filepath)))

    env_refs = _scan_env_refs(repo, [".ts", ".js", ".svelte"])
    return ParseResult(routes=routes, env_refs=env_refs)


def _parse_firebase(repo: Path) -> ParseResult:
    """Firebase route extraction from functions/index.js/.ts."""
    routes = []
    func_dir = repo / "functions"
    index_files = ["index.js", "index.ts", "src/index.js", "src/index.ts"]

    for idx_name in index_files:
        idx_path = func_dir / idx_name if func_dir.is_dir() else repo / idx_name
        if idx_path.exists():
            try:
                content = idx_path.read_text(errors="ignore")
            except OSError:
                continue
            # Match exports.functionName = functions.https.onRequest(...)
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
    """Extract HTTP method exports from a route file."""
    methods = []
    try:
        content = filepath.read_text(errors="ignore")
    except OSError:
        return ["GET"]
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        if re.search(rf'\bexport\s+(?:async\s+)?function\s+{method}\b', content):
            methods.append(method)
    return methods or ["GET"]


def _scan_env_refs(repo: Path, extensions: list[str]) -> list[EnvRef]:
    refs = []
    pattern = re.compile(r'process\.env\.(\w+)')
    for root, _dirs, files in os.walk(repo):
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
    refs = []
    # Match both os.environ.get("X") and os.environ["X"] / os.environ['X']
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

PARSERS = {
    "nextjs": _parse_nextjs,
    "express": _parse_express,
    "fastapi": _parse_fastapi,
    "flask": _parse_flask,
    "sveltekit": _parse_sveltekit,
    "firebase": _parse_firebase,
}


def parse_repo(repo_path: str, stack: str) -> ParseResult:
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
