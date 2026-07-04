"""Stack detector — heuristic scoring for 6 whitelisted stacks."""

from enum import Enum
from pathlib import Path
import json
from typing import Optional


class UnsupportedStackError(Exception):
    pass


class Stack(str, Enum):
    NEXTJS = "nextjs"
    EXPRESS = "express"
    FIREBASE = "firebase"
    FASTAPI = "fastapi"
    FLASK = "flask"
    SVELTEKIT = "sveltekit"


def _has_file(repo: Path, *patterns: str) -> bool:
    for pattern in patterns:
        if (repo / pattern).exists():
            return True
    return False


def _has_package_dep(repo: Path, dep_name: str) -> bool:
    pkg_path = repo / "package.json"
    if not pkg_path.exists():
        return False
    try:
        pkg = json.loads(pkg_path.read_text())
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        return dep_name in deps
    except (json.JSONDecodeError, OSError):
        return False


def _has_python_dep(repo: Path, dep_name: str) -> bool:
    req_path = repo / "requirements.txt"
    if req_path.exists():
        try:
            if dep_name in req_path.read_text():
                return True
        except OSError:
            pass
    toml_path = repo / "pyproject.toml"
    if toml_path.exists():
        try:
            if dep_name in toml_path.read_text():
                return True
        except OSError:
            pass
    return False


def detect_stack(repo_path: str) -> Stack:
    """Detect the stack of a repository at the given path.

    Returns Stack enum value. Raises UnsupportedStackError if no match.
    On polyglot (multiple matches), returns first decisive match by priority order.
    """
    repo = Path(repo_path)
    if not repo.is_dir():
        raise UnsupportedStackError(f"Not a directory: {repo_path}")

    rules = [
        # Next.js: package.json has next dep OR config file exists
        (lambda: _has_package_dep(repo, "next") or _has_file(repo, "next.config.js", "next.config.mjs", "next.config.ts"), Stack.NEXTJS),

        # SvelteKit: config file + kit dep
        (lambda: _has_file(repo, "svelte.config.js") and _has_package_dep(repo, "@sveltejs/kit"), Stack.SVELTEKIT),

        # Firebase: firebase.json or .firebaserc
        (lambda: _has_file(repo, "firebase.json", ".firebaserc"), Stack.FIREBASE),

        # FastAPI: Python dependency
        (lambda: _has_python_dep(repo, "fastapi"), Stack.FASTAPI),

        # Flask: Python dependency (after FastAPI check to avoid false match)
        (lambda: _has_python_dep(repo, "flask"), Stack.FLASK),

        # Express: package.json has express dep
        (lambda: _has_package_dep(repo, "express"), Stack.EXPRESS),
    ]

    for condition, stack in rules:
        try:
            if condition():
                return stack
        except Exception:
            continue

    raise UnsupportedStackError(f"No supported stack detected in {repo_path}. Supported: {[s.value for s in Stack]}")
