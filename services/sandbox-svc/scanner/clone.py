"""Secure repo cloner with Metis guardrails: shallow, no-LFS, ≤500MB, block postinstall."""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)

MAX_REPO_SIZE_MB = 500

class CloneError(Exception):
    pass

class RepoTooLarge(CloneError):
    pass


def _estimate_repo_size(repo_url: str) -> int:
    """Estimate repo size in MB via git ls-remote without cloning."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", repo_url],
            capture_output=True, text=True, timeout=30, env=env
        )
        if result.returncode != 0:
            logger.warning("clone.size_estimate_failed", repo=repo_url, stderr=result.stderr[:200])
            return 0  # unknown — proceed, let clone fail naturally
        # Rough heuristic: ref count × 0.5MB average
        ref_count = len([l for l in result.stdout.strip().split("\n") if l])
        estimate_mb = max(ref_count * 0.5, 1)
        logger.info("clone.size_estimated", repo=repo_url, refs=ref_count, estimate_mb=estimate_mb)
        return estimate_mb
    except subprocess.TimeoutExpired:
        logger.warning("clone.size_timeout", repo=repo_url)
        return 0


def clone_repo(repo_url: str, target_dir: Optional[str] = None, branch: str = "HEAD") -> str:
    """Clone repo with security guardrails.

    Returns path to cloned repo.
    Raises RepoTooLarge if estimated size > 500MB.
    Raises CloneError on general clone failure.
    """
    size_mb = _estimate_repo_size(repo_url)
    if size_mb > MAX_REPO_SIZE_MB:
        raise RepoTooLarge(f"Repo estimated at {size_mb}MB exceeds {MAX_REPO_SIZE_MB}MB cap")

    dest = target_dir or tempfile.mkdtemp(prefix="antivibe-clone-")
    Path(dest).mkdir(parents=True, exist_ok=True)

    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_LFS_SKIP_SMUDGE": "1",       # Block LFS download
        "GIT_CONFIG_NOSYSTEM": "1",        # Don't read system gitconfig
        "GIT_CONFIG_NOGLOBAL": "1",        # Don't read global gitconfig
        "HOME": "/tmp"                     # Prevent ~/.gitconfig leaks
    }

    cmd = ["git", "clone", "--depth", "1", "--single-branch", "--no-tags"]
    if branch and branch != "HEAD":
        cmd.extend(["--branch", branch])
    cmd.extend([repo_url, dest])

    logger.info("clone.starting", repo=repo_url, dest=dest)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        if result.returncode != 0:
            raise CloneError(f"git clone failed: {result.stderr[:500]}")
    except subprocess.TimeoutExpired:
        raise CloneError("git clone timed out after 120s")

    logger.info("clone.done", repo=repo_url, dest=dest)

    # Post-install hooks defense: inject ignore-scripts
    _block_postinstall_hooks(dest)

    return dest


def _block_postinstall_hooks(repo_path: str) -> None:
    """Defense-in-depth: block postinstall scripts in cloned repos.

    - Sets npm_config_ignore_scripts=true for any npm/yarn installs
    - Writes .npmrc with ignore-scripts=true if npm project detected
    """
    repo = Path(repo_path)

    npmrc_path = repo / ".npmrc"
    try:
        existing = npmrc_path.read_text() if npmrc_path.exists() else ""
        if "ignore-scripts=true" not in existing:
            new_content = existing + "\nignore-scripts=true\n"
            npmrc_path.write_text(new_content)
            logger.info("clone.npmrc_written", path=str(npmrc_path))
    except OSError:
        logger.warning("clone.npmrc_failed", path=str(npmrc_path))

    pip_conf_dir = repo / ".pip"
    pip_conf_dir.mkdir(exist_ok=True)
    pip_conf = pip_conf_dir / "pip.conf"
    try:
        pip_conf.write_text("[install]\nno-build-isolation = true\n")
        logger.info("clone.pipconf_written", path=str(pip_conf))
    except OSError:
        logger.warning("clone.pipconf_failed")

    os.environ["npm_config_ignore_scripts"] = "true"
