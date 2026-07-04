"""Stack detection: heuristic scoring for the 6 whitelisted runtime stacks.

The scanner pipeline is stack-specific — Next.js uses App Router conventions,
FastAPI uses decorator-based routing, and the analyzers downstream can't
make assumptions that work for all of them. So the first thing we do after
cloning is pick *one* stack to drive everything else.

Why heuristic and not a real manifest registry?
-----------------------------------------------
There is no reliable single source of truth:

  - `package.json` is missing for non-JS stacks.
  - Python stacks spread their signal across `requirements.txt` (pinned
    versions) and `pyproject.toml` (PEP 621 metadata) and `Pipfile` and
    `setup.py` — and not every repo uses all of them.
  - Firebase projects are often just a `firebase.json` + a sibling
    `functions/` directory with no Node manifest at the root.

A heuristic that *combines* multiple weak signals is more robust than any
single one. The rule order is a deliberate priority list, not a guess:
when two stacks match, the *first* rule wins (e.g. Next.js beats Express,
because a Next.js API route is still an Express-style app under the hood
and an unannotated Express dep is more often a transitive dep than the
primary framework).
"""

from enum import Enum
from pathlib import Path
import json
from typing import Optional


class UnsupportedStackError(Exception):
    """Raised when no rule matches. Caller decides whether to surface or default."""


class Stack(str, Enum):
    """The 6 stacks the scanner knows how to analyze. Values are wire-stable:

    serialized into findings, stored in the database, and referenced by
    downstream parsers. Adding a new stack requires updating `detect_stack`
    rules, `ast_parser.PARSERS`, and `config_flaws.ANALYZERS` together.
    """
    NEXTJS = "nextjs"
    EXPRESS = "express"
    FIREBASE = "firebase"
    FASTAPI = "fastapi"
    FLASK = "flask"
    SVELTEKIT = "sveltekit"


def _has_file(repo: Path, *patterns: str) -> bool:
    """True if any of the given filenames exist directly under `repo`.

    Used for config files (next.config.js, firebase.json) where the
    filename *is* the signal. Does not recurse — by convention, these
    files live at the repo root.
    """
    for pattern in patterns:
        if (repo / pattern).exists():
            return True
    return False


def _has_package_dep(repo: Path, dep_name: str) -> bool:
    """True if `dep_name` is in `package.json` dependencies or devDependencies.

    Both maps are merged because frameworks (e.g. next) are often listed
    in devDependencies for projects that *consume* Next.js as a build
    target rather than shipping it. Silently returns False on malformed
    JSON — a broken `package.json` is not a signal we want to act on.
    """
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
    """True if `dep_name` appears in either `requirements.txt` or `pyproject.toml`.

    Both formats are checked because Python projects frequently have one
    without the other (legacy `requirements.txt`-only projects, modern
    `pyproject.toml`-only projects). The check is substring-based rather
    than parsed — false positives are bounded (e.g. matching `flask` in
    `flask-cors` is fine because that *is* still a flask dep).
    """
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
    """Detect the primary stack of a cloned repository.

    Rules are evaluated in priority order — the *first* match wins. This
    is intentional: a repo with both a `next.config.js` and an
    `express` dep in `package.json` is detected as Next.js, because the
    Next.js framework pulls Express in as a transitive dependency.
    The FastAPI→Flask ordering applies the same logic in reverse: a
    `requirements.txt` listing both is a FastAPI app that also happens
    to depend on flask (e.g. for an admin UI), not a Flask app that
    happens to use FastAPI.

    Returns:
        The detected Stack enum value.

    Raises:
        UnsupportedStackError: no rule matched (repo is some other
            stack, or no manifest is present).
    """
    repo = Path(repo_path)
    if not repo.is_dir():
        raise UnsupportedStackError(f"Not a directory: {repo_path}")

    # Each rule is `(predicate, stack)`. The list is ordered: more
    # specific / framework-defining signals come first. Tied signals
    # resolve to whichever appears earlier in this list.
    rules = [
        # Next.js: the `next` dep is the canonical signal, but we also
        # accept a config file alone — projects that have just switched
        # frameworks sometimes leave a stale package.json around.
        (lambda: _has_package_dep(repo, "next") or _has_file(repo, "next.config.js", "next.config.mjs", "next.config.ts"), Stack.NEXTJS),

        # SvelteKit: both signals are required because a bare
        # `svelte.config.js` can exist in legacy Svelte (non-Kit) projects.
        (lambda: _has_file(repo, "svelte.config.js") and _has_package_dep(repo, "@sveltejs/kit"), Stack.SVELTEKIT),

        # Firebase: project root marker. `.firebaserc` is a workspace
        # alias file; `firebase.json` is the project config.
        (lambda: _has_file(repo, "firebase.json", ".firebaserc"), Stack.FIREBASE),

        # FastAPI must beat Flask because FastAPI apps commonly pull
        # flask in for an internal health-check route.
        (lambda: _has_python_dep(repo, "fastapi"), Stack.FASTAPI),

        # Flask: only reached if FastAPI wasn't a hit. Stays ahead of
        # Express in the list even though it's a different language,
        # because the tests pin this priority (see test_fastapi_beats_flask).
        (lambda: _has_python_dep(repo, "flask"), Stack.FLASK),

        # Express: a bare `express` dep is weaker than the
        # framework-specific signals above (Express is often transitive),
        # so it lives at the bottom of the priority list.
        (lambda: _has_package_dep(repo, "express"), Stack.EXPRESS),
    ]

    # A throwing predicate (e.g. file I/O race during a parallel clone)
    # should not abort the whole detection. We treat it as "no match"
    # and let later rules take their turn.
    for condition, stack in rules:
        try:
            if condition():
                return stack
        except Exception:
            continue

    raise UnsupportedStackError(f"No supported stack detected in {repo_path}. Supported: {[s.value for s in Stack]}")
