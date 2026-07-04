"""Tests for AST parser across all 6 stacks."""

import tempfile
from pathlib import Path
from scanner.ast_parser import parse_repo, ParseResult


def _write_file(base: Path, relpath: str, content: str):
    filepath = base / relpath
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content)


class TestNextJS:
    def test_app_router_routes(self, tmp_path):
        _write_file(tmp_path, "app/api/users/route.ts", "export async function GET() {}")
        _write_file(tmp_path, "app/api/users/[id]/route.ts", "export function GET() {}\nexport function PATCH() {}")
        result = parse_repo(str(tmp_path), "nextjs")
        paths = {r.path for r in result.routes}
        assert "/api/users" in paths
        assert any(":id" in r.path and "api/users" in r.path for r in result.routes)

    def test_env_refs_detected(self, tmp_path):
        _write_file(tmp_path, "app/config.ts", "const url = process.env.NEXT_PUBLIC_URL;")
        result = parse_repo(str(tmp_path), "nextjs")
        env_names = {e.name for e in result.env_refs}
        assert "NEXT_PUBLIC_URL" in env_names


class TestExpress:
    def test_express_routes(self, tmp_path):
        _write_file(tmp_path, "app.js", 'app.get("/api/users", handler);\napp.post("/api/login", login);')
        result = parse_repo(str(tmp_path), "express")
        paths = {r.path for r in result.routes}
        assert "/api/users" in paths
        assert "/api/login" in paths


class TestFastAPI:
    def test_fastapi_routes(self, tmp_path):
        _write_file(tmp_path, "main.py",
            '@app.get("/items")\n@app.post("/items")\n@app.put("/items/{item_id}")')
        result = parse_repo(str(tmp_path), "fastapi")
        paths = {r.path for r in result.routes}
        assert "/items" in paths
        assert any("{item_id}" in r.path for r in result.routes)

    def test_python_env_refs(self, tmp_path):
        _write_file(tmp_path, "config.py",
            'DATABASE_URL = os.environ.get("DATABASE_URL")\nSECRET = os.environ["SECRET"]')
        result = parse_repo(str(tmp_path), "fastapi")
        env_names = {e.name for e in result.env_refs}
        assert "DATABASE_URL" in env_names
        assert "SECRET" in env_names


class TestFlask:
    def test_flask_routes(self, tmp_path):
        _write_file(tmp_path, "app.py", '@app.route("/home")\n@app.route("/api/data")')
        result = parse_repo(str(tmp_path), "flask")
        paths = {r.path for r in result.routes}
        assert "/home" in paths
        assert "/api/data" in paths


class TestSvelteKit:
    def test_sveltekit_server_routes(self, tmp_path):
        _write_file(tmp_path, "src/routes/api/users/+server.ts",
            'export function GET() {}\nexport function POST() {}')
        _write_file(tmp_path, "src/routes/api/health/+server.ts",
            'export function GET() {}')
        result = parse_repo(str(tmp_path), "sveltekit")
        assert len(result.routes) >= 2
        methods_all = set()
        for r in result.routes:
            methods_all.update(r.methods)
        assert "GET" in methods_all
        assert "POST" in methods_all


class TestFirebase:
    def test_firebase_functions(self, tmp_path):
        func_dir = tmp_path / "functions"
        func_dir.mkdir()
        (func_dir / "index.js").write_text(
            'exports.helloWorld = functions.https.onRequest((req, res) => {});\n'
            'exports.getUser = functions.https.onCall((data, context) => {});'
        )
        result = parse_repo(str(tmp_path), "firebase")
        paths = {r.path for r in result.routes}
        assert "/helloWorld" in paths
        assert "/getUser" in paths


class TestResilience:
    def test_malformed_file_does_not_crash(self, tmp_path):
        _write_file(tmp_path, "app/api/broken/route.ts", "thiss is nott typescriptt {{{}}}}")
        _write_file(tmp_path, "app/api/ok/route.ts", "export function GET() {}")
        result = parse_repo(str(tmp_path), "nextjs")
        # Should still find the valid route
        paths = {r.path for r in result.routes}
        assert any("ok" in p for p in paths)

    def test_unsupported_stack_returns_empty(self, tmp_path):
        result = parse_repo(str(tmp_path), "ruby_on_rails")
        assert len(result.routes) == 0
        assert len(result.env_refs) == 0

    def test_not_a_directory_returns_empty(self):
        result = parse_repo("/nonexistent/path/xyz", "nextjs")
        assert len(result.routes) == 0
