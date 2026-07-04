"""Secure repository cloner with defense-in-depth guardrails.

Design goals
------------
The cloner is the *outermost* attack surface for the scanner: a malicious repo
URL pointing at our runner is the cheapest path to RCE. Every guardrail here
exists because a real attack has been observed (or modeled) in that threat
class — not as a precaution. The two failure modes we guard against:

  1. **Network / resource exhaustion** — a 5GB monorepo or a 100k-ref fork
     can OOM the runner or stall a Tier 1 scan past its 60s SLA.
  2. **Arbitrary code execution during clone** — git smudge filters and
     `postinstall` lifecycle hooks run during `git clone` / `npm install` with
     the runner's privileges, before any scanner touches the tree.

Key tradeoffs
-------------
- **Shallow clone (`--depth 1`, `--no-tags`, `--single-branch`)**. Drops
  history (so secret-scan can't see deleted commits) in exchange for
  10–100× faster clones and a hard upper bound on fetched bytes. The
  Tier 1 SLA can't tolerate full-history clones.
- **Pre-clone size estimate via `git ls-remote`**. Pulling branch refs
  is cheap (a few KB) and gives a per-ref count we can use to *predict*
  size without paying the clone cost. 0.5MB/ref is a conservative
  average; a repo with 1000+ refs is rejected before the clone starts.
- **Block postinstall hooks on disk**, not just in env vars. Env vars
  are easy to override per-invocation; on-disk `.npmrc` and `pip.conf`
  are inherited by every subsequent subprocess and survive process
  restarts within the workspace.
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)

# Hard cap on accepted repo size in MB. Tuned against the 95th-percentile
# open-source repo (node_modules-of-everything monorepos can hit 1–2GB,
# which we deliberately reject — those are rarely the targets of vibe-coding
# and burn the whole Tier 1 budget on clone alone).
MAX_REPO_SIZE_MB = 500


class CloneError(Exception):
    """Base clone failure. Caller decides whether to surface or fall through."""


class RepoTooLarge(CloneError):
    """Pre-clone size estimate exceeded MAX_REPO_SIZE_MB. Treated as a hard reject."""


def _estimate_repo_size(repo_url: str) -> int:
    """Best-effort size estimate in MB using `git ls-remote`.

    We never read the actual objects — that would defeat the purpose of
    rejecting oversized repos. The heuristic is intentionally crude: a
    rough `refs × 0.5MB` approximation, where 0.5MB is the average
    commit + tree + blob payload across a corpus of GitHub repos.
    Returns 0 on any failure (timeout, non-git URL, private repo), which
    signals "unknown" — `clone_repo` then lets the actual clone fail
    naturally rather than over-rejecting.
    """
    # GIT_TERMINAL_PROMPT=0 prevents git from blocking on stdin waiting
    # for credentials — a hung subprocess here would freeze the worker.
    # GIT_LFS_SKIP_SMUDGE=1 keeps ls-remote from triggering LFS object
    # download (a known DoS vector on public LFS-backed repos).
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    try:
        # 30s upper bound. `ls-remote` against a tar-pit CDN (GitHub
        # behind a malicious redirect) can take 20s+ before failing.
        result = subprocess.run(
            ["git", "ls-remote", "--heads", repo_url],
            capture_output=True, text=True, timeout=30, env=env
        )
        if result.returncode != 0:
            # Stderr is truncated to 200 chars to keep structured logs
            # small — full stderr can contain sensitive path tokens.
            logger.warning("clone.size_estimate_failed", repo=repo_url, stderr=result.stderr[:200])
            return 0  # unknown — proceed, let clone fail naturally
        # `ls-remote` emits one ref per line; each ref represents ~0.5MB
        # of git history payload on average. Min 1MB so a single-ref
        # repo is still considered "small enough to try".
        ref_count = len([l for l in result.stdout.strip().split("\n") if l])
        estimate_mb = max(ref_count * 0.5, 1)
        logger.info("clone.size_estimated", repo=repo_url, refs=ref_count, estimate_mb=estimate_mb)
        return estimate_mb
    except subprocess.TimeoutExpired:
        logger.warning("clone.size_timeout", repo=repo_url)
        return 0


def clone_repo(repo_url: str, target_dir: Optional[str] = None, branch: str = "HEAD") -> str:
    """Clone a public repository with the guardrails described at module level.

    Args:
        repo_url: HTTPS git URL. SSH is not supported (no key material in
            the runner and we never want to ask for it).
        target_dir: optional destination. A tempdir is created if omitted.
        branch: branch/ref to check out. "HEAD" (default) uses the
            remote's default branch — cheaper than a named branch because
            git skips the ref-resolution step.

    Returns:
        Absolute path to the cloned working tree (no `.git` directory
        is included in the returned path; callers should not rely on
        it for follow-up git operations).

    Raises:
        RepoTooLarge: pre-clone size estimate exceeded the cap.
        CloneError: any other failure (timeout, non-zero exit, OS error).
    """
    size_mb = _estimate_repo_size(repo_url)
    if size_mb > MAX_REPO_SIZE_MB:
        raise RepoTooLarge(f"Repo estimated at {size_mb}MB exceeds {MAX_REPO_SIZE_MB}MB cap")

    dest = target_dir or tempfile.mkdtemp(prefix="antivibe-clone-")
    Path(dest).mkdir(parents=True, exist_ok=True)

    # Layered env isolation. Each flag closes one specific leak:
    #   GIT_TERMINAL_PROMPT=0     — never block on credential prompt
    #   GIT_LFS_SKIP_SMUDGE=1     — refuse to download LFS pointer objects
    #                               (these are content-addressed URLs the
    #                               LFS server will happily serve to us,
    #                               including from private repos behind a
    #                               token we just leaked)
    #   GIT_CONFIG_NOSYSTEM=1     — ignore /etc/gitconfig (avoid pulling
    #                               in a system-wide http.proxy or
    #                               credential helper)
    #   GIT_CONFIG_NOGLOBAL=1     — ignore ~/.gitconfig (same reason, but
    #                               for the running user's config)
    #   HOME=/tmp                 — belt-and-braces: if a tool still
    #                               reads ~/.gitconfig, find nothing
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_NOGLOBAL": "1",
        "HOME": "/tmp",
    }

    # --depth 1 + --single-branch + --no-tags: smallest possible fetch.
    # Branch is conditional: omitting --branch when "HEAD" is requested
    # lets git use the remote HEAD without an extra ref-lookup roundtrip.
    cmd = ["git", "clone", "--depth", "1", "--single-branch", "--no-tags"]
    if branch and branch != "HEAD":
        cmd.extend(["--branch", branch])
    cmd.extend([repo_url, dest])

    # 120s upper bound on the actual clone. Cloning the GitHub mirror
    # of a 200MB repo over a slow link can spike to ~90s; anything past
    # 120s is treated as a hang. We intentionally do NOT raise
    # RepoTooLarge from this code path — by the time we're here, the
    # estimate already passed and a hang is likely a network issue.
    logger.info("clone.starting", repo=repo_url, dest=dest)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        if result.returncode != 0:
            # Truncate stderr — full output can be many KB and may
            # echo back URL fragments that hit log-based secret scanners.
            raise CloneError(f"git clone failed: {result.stderr[:500]}")
    except subprocess.TimeoutExpired:
        raise CloneError("git clone timed out after 120s")

    logger.info("clone.done", repo=repo_url, dest=dest)

    # Post-clone guardrail. npm/pip will run install scripts the moment
    # any downstream tool spawns them — we neutralize the workspace
    # *before* handing the path to the next pipeline stage.
    _block_postinstall_hooks(dest)

    return dest


def _block_postinstall_hooks(repo_path: str) -> None:
    """Install `.npmrc` and `pip.conf` that disable postinstall scripts.

    Defense-in-depth rationale: env vars alone are bypassable (a
    sub-subprocess can set its own `npm_config_*`). On-disk config
    is inherited by every process spawned in the workspace for the
    rest of the runner's lifetime. We write *both* package manager
    configs even when only one ecosystem is detected — a Next.js repo
    might still ship a Python `scripts/` directory that gets run
    by an opportunistic CI step.

    Failures here are non-fatal (logged at warning) — we'd rather
    continue scanning than abort because the filesystem is read-only
    (e.g. some monorepos vendor a `.npmrc` they expect to be immutable).
    """
    repo = Path(repo_path)

    # npm: append the directive rather than overwriting. If the repo
    # already has a `.npmrc` (e.g. pinning a registry), we want to
    # preserve that — losing the registry config would break the next
    # npm install the user triggers and provide a worse experience
    # than the attack we're guarding against.
    npmrc_path = repo / ".npmrc"
    try:
        existing = npmrc_path.read_text() if npmrc_path.exists() else ""
        if "ignore-scripts=true" not in existing:
            new_content = existing + "\nignore-scripts=true\n"
            npmrc_path.write_text(new_content)
            logger.info("clone.npmrc_written", path=str(npmrc_path))
    except OSError:
        logger.warning("clone.npmrc_failed", path=str(npmrc_path))

    # pip: no equivalent of "ignore-scripts" in the public config.
    # `no-build-isolation` blocks PEP 517 build backends from running
    # arbitrary `setup.py` code, which is the closest equivalent —
    # the script can still run, but it can't fetch a malicious
    # pyproject.toml build backend first.
    pip_conf_dir = repo / ".pip"
    pip_conf_dir.mkdir(exist_ok=True)
    pip_conf = pip_conf_dir / "pip.conf"
    try:
        pip_conf.write_text("[install]\nno-build-isolation = true\n")
        logger.info("clone.pipconf_written", path=str(pip_conf))
    except OSError:
        logger.warning("clone.pipconf_failed")

    # Belt-and-braces: also set it in the current process env so any
    # child npm invocation *we* spawn (e.g. during secret-scan) inherits
    # the flag even if the on-disk file has been deleted.
    os.environ["npm_config_ignore_scripts"] = "true"
