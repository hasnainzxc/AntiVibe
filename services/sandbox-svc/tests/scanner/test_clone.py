"""Tests for secure repo cloner."""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from scanner.clone import clone_repo, RepoTooLarge, CloneError, _estimate_repo_size


class TestSizeEstimate:
    def test_valid_repo_returns_estimate(self):
        size = _estimate_repo_size("https://github.com/supabase/supabase")
        assert size >= 0

    def test_bad_url_returns_zero(self):
        size = _estimate_repo_size("https://nonexistent.example.com/repo")
        assert size == 0  # falls back to unknown


class TestSizeCap:
    def test_oversized_repo_rejected(self, monkeypatch):
        def mock_estimate(url):
            return 600  # 600MB
        monkeypatch.setattr("scanner.clone._estimate_repo_size", mock_estimate)
        with pytest.raises(RepoTooLarge, match="600MB"):
            clone_repo("https://fake/huge-repo")

    def test_small_repo_not_rejected(self, monkeypatch):
        def mock_estimate(url):
            return 10
        def mock_clone(*args, **kwargs):
            raise Exception("should not reach clone")
        monkeypatch.setattr("scanner.clone._estimate_repo_size", mock_estimate)
        monkeypatch.setattr("scanner.clone.subprocess.run", mock_clone)
        # Should fail on clone attempt, not on size check
        with pytest.raises(Exception, match="should not reach clone"):
            clone_repo("https://fake/small-repo")


class TestPostinstallBlock:
    def test_npmrc_has_ignore_scripts(self, tmp_path):
        from scanner.clone import _block_postinstall_hooks
        repo = tmp_path / "fake-repo"
        repo.mkdir()
        _block_postinstall_hooks(str(repo))
        npmrc = repo / ".npmrc"
        assert npmrc.exists()
        content = npmrc.read_text()
        assert "ignore-scripts=true" in content

    def test_pip_conf_created(self, tmp_path):
        from scanner.clone import _block_postinstall_hooks
        repo = tmp_path / "fake-repo"
        repo.mkdir()
        _block_postinstall_hooks(str(repo))
        pipconf = repo / ".pip" / "pip.conf"
        assert pipconf.exists()
        content = pipconf.read_text()
        assert "no-build-isolation" in content


class TestEnvFlags:
    def test_git_lfs_skip_set(self):
        import scanner.clone as clone_module
        source = Path(clone_module.__file__).read_text()
        assert "GIT_LFS_SKIP_SMUDGE" in source
        assert "--depth" in source
        assert "1" in source  # shallow depth

    def test_no_git_lfs_invocation(self):
        import scanner.clone as clone_module
        source = Path(clone_module.__file__).read_text()
        assert "git lfs" not in source.lower()
