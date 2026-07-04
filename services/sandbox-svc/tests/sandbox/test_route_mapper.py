"""Tests for route mapper."""

import tempfile
from pathlib import Path
from scanner.ast_parser import RouteShape, ParseResult
from sandbox.route_mapper import (
    build_route_index,
    RouteIndexEntry,
    _has_auth_pattern,
    _normalize_path,
    _is_sensitive_route,
)


def _make_route(path: str, methods: list[str], file_path: str = "", auth_required_on_shape: bool = False) -> RouteShape:
    """Helper: create a RouteShape for testing."""
    shape = RouteShape(path=path, methods=methods, file=file_path)
    shape.auth_required = auth_required_on_shape
    return shape


class TestAuthDetection:
    def test_nextauth_pattern(self):
        content = "import { getServerSession } from 'next-auth';"
        assert _has_auth_pattern(content, "nextauth")

    def test_clerk_pattern(self):
        content = "import { auth } from '@clerk/nextjs';"
        assert _has_auth_pattern(content, "clerk")

    def test_supabase_pattern(self):
        content = "const { data } = await supabase.auth.getUser();"
        assert _has_auth_pattern(content, "supabase")

    def test_no_pattern(self):
        content = "export async function GET() { return Response.json({}); }"
        assert not _has_auth_pattern(content, "nextauth")


class TestPathNormalization:
    def test_nextjs_dynamic(self):
        assert _normalize_path("/api/users/[id]") == "/api/users/:id"

    def test_fastapi_dynamic(self):
        assert _normalize_path("/items/{item_id}") == "/items/:item_id"

    def test_already_normalized(self):
        assert _normalize_path("/api/users/:userId") == "/api/users/:userId"


class TestSensitiveRoute:
    def test_api_users_is_sensitive(self):
        assert _is_sensitive_route("/api/users")

    def test_home_is_not_sensitive(self):
        assert not _is_sensitive_route("/")


class TestBuildRouteIndex:
    def test_auth_route_marked(self, tmp_path):
        """Route file with auth import gets auth_required=True."""
        route_file = tmp_path / "route.ts"
        route_file.write_text("import { getServerSession } from 'next-auth';\nexport async function GET() {}")
        
        routes = [_make_route("/api/users", ["GET"], str(route_file))]
        ast = ParseResult(routes=routes)
        index = build_route_index(ast, "nextjs", "nextauth")
        
        assert len(index) == 1
        assert index[0].auth_required is True

    def test_no_auth_route_not_marked(self, tmp_path):
        """Route file without auth gets auth_required=False."""
        route_file = tmp_path / "public.ts"
        route_file.write_text("export async function GET() { return Response.json({}); }")
        
        routes = [_make_route("/api/public", ["GET"], str(route_file))]
        ast = ParseResult(routes=routes)
        index = build_route_index(ast, "nextjs", "nextauth")
        
        assert len(index) == 1
        assert index[0].auth_required is False

    def test_multiple_routes(self, tmp_path):
        auth_file = tmp_path / "auth-route.ts"
        auth_file.write_text("import { auth } from '@clerk/nextjs';\nexport async function GET() {}")
        
        public_file = tmp_path / "public-route.ts"
        public_file.write_text("export async function GET() {}")
        
        routes = [
            _make_route("/api/protected", ["GET"], str(auth_file)),
            _make_route("/api/public", ["GET"], str(public_file)),
        ]
        ast = ParseResult(routes=routes)
        index = build_route_index(ast, "nextjs", "clerk")
        
        assert len(index) == 2
        protected = next(r for r in index if r.path == "/api/protected")
        public = next(r for r in index if r.path == "/api/public")
        assert protected.auth_required is True
        assert public.auth_required is False
