"""Tests for stack detector."""

import json
from pathlib import Path
import pytest
from scanner.detect_stack import detect_stack, Stack, UnsupportedStackError


def _make_package_json(repo: Path, deps: dict):
    """Helper: write package.json with given dependencies."""
    pkg = {"dependencies": deps}
    (repo / "package.json").write_text(json.dumps(pkg))


def _make_req_txt(repo: Path, content: str):
    (repo / "requirements.txt").write_text(content)


class TestNextJS:
    def test_detect_by_package_json(self, tmp_path):
        _make_package_json(tmp_path, {"next": "14.0.0"})
        (tmp_path / "app").mkdir()
        assert detect_stack(str(tmp_path)) == Stack.NEXTJS

    def test_detect_by_config(self, tmp_path):
        (tmp_path / "next.config.js").write_text("module.exports = {}")
        assert detect_stack(str(tmp_path)) == Stack.NEXTJS


class TestExpress:
    def test_detect_express(self, tmp_path):
        _make_package_json(tmp_path, {"express": "4.18.0"})
        assert detect_stack(str(tmp_path)) == Stack.EXPRESS

    def test_express_overridden_by_nextjs(self, tmp_path):
        """Polyglot: Next.js beats Express."""
        _make_package_json(tmp_path, {"next": "14.0.0", "express": "4.18.0"})
        assert detect_stack(str(tmp_path)) == Stack.NEXTJS


class TestFastAPI:
    def test_detect_fastapi(self, tmp_path):
        _make_req_txt(tmp_path, "fastapi==0.110.0\nuvicorn\n")
        assert detect_stack(str(tmp_path)) == Stack.FASTAPI


class TestFlask:
    def test_detect_flask(self, tmp_path):
        _make_req_txt(tmp_path, "flask==3.0.0\n")
        assert detect_stack(str(tmp_path)) == Stack.FLASK

    def test_fastapi_beats_flask(self, tmp_path):
        _make_req_txt(tmp_path, "fastapi\nflask\n")
        assert detect_stack(str(tmp_path)) == Stack.FASTAPI


class TestSvelteKit:
    def test_detect_sveltekit(self, tmp_path):
        _make_package_json(tmp_path, {"@sveltejs/kit": "2.0.0"})
        (tmp_path / "svelte.config.js").write_text("export default {}")
        assert detect_stack(str(tmp_path)) == Stack.SVELTEKIT


class TestUnsupported:
    def test_raises_on_unsupported(self, tmp_path):
        with pytest.raises(UnsupportedStackError, match="No supported stack detected"):
            detect_stack(str(tmp_path))

    def test_raises_for_rails(self, tmp_path):
        (tmp_path / "Gemfile").write_text("gem 'rails'")
        with pytest.raises(UnsupportedStackError):
            detect_stack(str(tmp_path))

    def test_not_a_directory(self):
        with pytest.raises(UnsupportedStackError):
            detect_stack("/nonexistent/path/12345")
