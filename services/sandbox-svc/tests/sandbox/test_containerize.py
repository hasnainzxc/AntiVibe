"""Tests for per-stack Dockerfile generator."""

import re
from pathlib import Path

import pytest

from sandbox.containerize import (
    TEMPLATES,
    UNSUPPORTED_STACK_ERROR,
    generate_dockerfile,
    write_dockerfile,
)
from scanner.detect_stack import Stack


def _make_fixture(base: Path, files: dict):
    """Create fixture files in base directory."""
    for relpath, content in files.items():
        filepath = base / relpath
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content)


class TestDockerfile:
    def test_nextjs_template(self):
        dockerfile = generate_dockerfile(Stack.NEXTJS, Path("/tmp/repo"))
        assert "FROM node:20-alpine" in dockerfile
        assert "EXPOSE 3000" in dockerfile
        assert "pnpm build" in dockerfile

    def test_nextjs_uses_standalone_build(self):
        """Next.js should use multi-stage build for standalone output."""
        dockerfile = generate_dockerfile(Stack.NEXTJS, Path("/tmp/repo"))
        assert "AS builder" in dockerfile
        assert ".next/standalone" in dockerfile
        assert "NEXT_TELEMETRY_DISABLED" in dockerfile

    def test_express_template(self, tmp_path):
        _make_fixture(tmp_path, {"package.json": '{"dependencies":{"express":"4.18.0"}}'})
        dockerfile = generate_dockerfile(Stack.EXPRESS, tmp_path)
        assert "EXPOSE 8000" in dockerfile
        assert "dist/index.js" in dockerfile

    def test_firebase_template(self, tmp_path):
        _make_fixture(tmp_path, {"firebase.json": "{}"})
        dockerfile = generate_dockerfile(Stack.FIREBASE, tmp_path)
        assert "firebase" in dockerfile.lower()
        assert "emulators:start" in dockerfile
        assert "antivibe-sandbox" in dockerfile

    def test_firebase_exposes_emulator_ports(self):
        """Firebase template must expose standard emulator ports."""
        dockerfile = generate_dockerfile(Stack.FIREBASE, Path("/tmp/repo"))
        assert "4000" in dockerfile
        assert "5001" in dockerfile

    def test_fastapi_template(self, tmp_path):
        _make_fixture(tmp_path, {"requirements.txt": "fastapi\nuvicorn\n"})
        dockerfile = generate_dockerfile(Stack.FASTAPI, tmp_path)
        assert "uvicorn" in dockerfile
        assert "app:app" in dockerfile
        assert "EXPOSE 8000" in dockerfile
        assert "python:3.12-slim" in dockerfile

    def test_flask_template(self, tmp_path):
        _make_fixture(tmp_path, {"requirements.txt": "flask\ngunicorn\n"})
        dockerfile = generate_dockerfile(Stack.FLASK, tmp_path)
        assert "gunicorn" in dockerfile
        assert "EXPOSE 5000" in dockerfile
        assert "python:3.12-slim" in dockerfile

    def test_sveltekit_template(self, tmp_path):
        _make_fixture(
            tmp_path,
            {
                "svelte.config.js": "export default {}",
                "package.json": '{"dependencies":{"@sveltejs/kit":"2.0.0"}}',
            },
        )
        dockerfile = generate_dockerfile(Stack.SVELTEKIT, tmp_path)
        assert "EXPOSE 4173" in dockerfile
        assert "preview" in dockerfile


class TestTemplateRegistry:
    def test_all_six_stacks_have_templates(self):
        """All 6 whitelisted stacks must have a template."""
        expected = {
            Stack.NEXTJS,
            Stack.EXPRESS,
            Stack.FIREBASE,
            Stack.FASTAPI,
            Stack.FLASK,
            Stack.SVELTEKIT,
        }
        assert set(TEMPLATES.keys()) == expected

    def test_no_extra_stacks(self):
        """Registry must only contain whitelisted stacks."""
        assert len(TEMPLATES) == 6


class TestUnsupportedStack:
    def test_raises_on_unknown_stack(self):
        with pytest.raises(ValueError, match=re.escape(UNSUPPORTED_STACK_ERROR)):
            generate_dockerfile("ruby_on_rails", Path("/tmp"))

    def test_error_message_contains_stack_value(self):
        """Error message should include the rejected stack value."""
        with pytest.raises(ValueError) as excinfo:
            generate_dockerfile("django", Path("/tmp"))
        assert UNSUPPORTED_STACK_ERROR in str(excinfo.value)
        assert "django" in str(excinfo.value)

    def test_none_stack_rejected(self):
        with pytest.raises(ValueError, match=re.escape(UNSUPPORTED_STACK_ERROR)):
            generate_dockerfile(None, Path("/tmp"))


class TestWriteDockerfile:
    def test_writes_to_output_dir(self, tmp_path):
        """Dockerfile is written to output_dir, NOT repo root."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _make_fixture(repo, {"package.json": '{"dependencies":{"next":"14.0.0"}}'})

        output = tmp_path / "scratch"
        path = write_dockerfile(Stack.NEXTJS, repo, output)

        assert path.exists()
        assert path.name == "Dockerfile.antivibe"
        assert "FROM node:20-alpine" in path.read_text()

    def test_does_not_write_to_repo(self, tmp_path):
        """Dockerfile is NOT written inside the user's repo."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _make_fixture(repo, {"package.json": '{"dependencies":{"next":"14.0.0"}}'})

        output = tmp_path / "scratch"
        write_dockerfile(Stack.NEXTJS, repo, output)

        assert not (repo / "Dockerfile.antivibe").exists()
        assert not (repo / "Dockerfile").exists()

    def test_creates_output_dir_if_missing(self, tmp_path):
        """write_dockerfile must create output_dir recursively."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _make_fixture(repo, {"package.json": '{"dependencies":{"express":"4.18.0"}}'})

        nested_output = tmp_path / "deeply" / "nested" / "scratch"
        assert not nested_output.exists()

        path = write_dockerfile(Stack.EXPRESS, repo, nested_output)

        assert nested_output.exists()
        assert path.exists()
        assert path.parent == nested_output

    def test_returns_path_object(self, tmp_path):
        """write_dockerfile should return a Path, not a string."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _make_fixture(repo, {"package.json": '{"dependencies":{"next":"14.0.0"}}'})

        path = write_dockerfile(Stack.NEXTJS, repo, tmp_path / "out")

        assert isinstance(path, Path)

    def test_unsupported_stack_raises_on_write(self, tmp_path):
        """write_dockerfile must also reject unsupported stacks."""
        repo = tmp_path / "repo"
        repo.mkdir()

        with pytest.raises(ValueError, match=re.escape(UNSUPPORTED_STACK_ERROR)):
            write_dockerfile("rails", repo, tmp_path / "out")

    def test_write_all_six_stacks(self, tmp_path):
        """Every whitelisted stack should be writable without error."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _make_fixture(
            repo,
            {
                "package.json": '{"dependencies":{"next":"14.0.0","express":"4.18.0"}}',
                "firebase.json": "{}",
                "svelte.config.js": "export default {}",
                "requirements.txt": "fastapi\nflask\nuvicorn\ngunicorn\n",
            },
        )

        for stack in [
            Stack.NEXTJS,
            Stack.EXPRESS,
            Stack.FIREBASE,
            Stack.FASTAPI,
            Stack.FLASK,
            Stack.SVELTEKIT,
        ]:
            path = write_dockerfile(stack, repo, tmp_path / f"out_{stack.value}")
            assert path.exists()
            assert path.read_text().startswith("FROM")
