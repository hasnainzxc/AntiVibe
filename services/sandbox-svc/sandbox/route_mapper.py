"""Per-stack route mapper — builds route index with auth_required inference.

Takes AST parser output and infers whether each route requires authentication
by checking for auth library imports and usage patterns.

Normalizes route params to :param convention (e.g., [id] → :id).
"""

from dataclasses import dataclass, field
from pathlib import Path
from scanner.ast_parser import ParseResult, RouteShape, parse_repo
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RouteIndexEntry:
    path: str
    methods: list[str]
    params: dict = field(default_factory=dict)
    auth_required: bool = False
    auth_stack: str = ""
    file_path: str = ""
    line: int = 0


# Auth detection patterns per stack
AUTH_PATTERNS = {
    "nextauth": [
        "getServerSession",
        "getSession",
        "NextAuth(",
        "authOptions",
        "import { auth } from",
        "import { getServerSession }",
    ],
    "clerk": [
        "auth()",
        "currentUser()",
        "import { auth } from '@clerk",
        "import { currentUser } from '@clerk",
        "authMiddleware",
    ],
    "firebase": [
        "onAuthStateChanged",
        "signInWithEmailAndPassword",
        "getAuth(",
        "requireAuth",
        "createSessionCookie",
    ],
    "supabase": [
        "supabase.auth.getUser()",
        "supabase.auth.getSession()",
        "createServerClient",
        "createClientComponentClient",
        "@supabase/ssr",
    ],
    "custom": [
        "JWT_SECRET",
        "jwt.sign(",
        "jwt.verify(",
        "jsonwebtoken",
        "verifyToken(",
        "authenticateToken",
        "authMiddleware",
        "requireAuth(",
    ],
}

# Route patterns that likely serve sensitive data
SENSITIVE_PATTERNS = [
    "/api/users",
    "/api/admin",
    "/api/profile",
    "/api/account",
    "/api/data",
    "/api/projects",
    "/api/universities",
    "/api/documents",
    "/api/settings",
    "/admin",
    "/dashboard",
]


def _has_auth_pattern(file_content: str, auth_stack: str) -> bool:
    """Check if file content contains auth patterns for the given auth stack."""
    patterns = AUTH_PATTERNS.get(auth_stack, [])
    for pattern in patterns:
        if pattern in file_content:
            return True
    return False


def _normalize_path(path: str) -> str:
    """Normalize route path placeholders to :param convention.

    Next.js [id] → :id
    FastAPI {item_id} → :item_id
    Express :userId → already normalized
    """
    import re
    # Next.js: [param] → :param
    path = re.sub(r'\[(\w+)\]', r':\1', path)
    # FastAPI: {param} → :param
    path = re.sub(r'\{(\w+)\}', r':\1', path)
    return path


def _is_sensitive_route(path: str) -> bool:
    """Check if route path suggests it serves sensitive data."""
    normalized = _normalize_path(path)
    for pattern in SENSITIVE_PATTERNS:
        if pattern in normalized:
            return True
    return False


def build_route_index(ast_result: ParseResult, stack: str, auth_stack: str) -> list[RouteIndexEntry]:
    """Build route index from AST parser results.

    Args:
        ast_result: Output from scanner.ast_parser.parse_repo()
        stack: Detected stack (nextjs, express, etc.)
        auth_stack: Detected auth library (nextauth, clerk, etc.)

    Returns:
        List of RouteIndexEntry with auth_required flags
    """
    entries = []

    for route in ast_result.routes:
        # Try to read the source file for auth pattern detection
        file_path = Path(route.file) if hasattr(route, 'file') and route.file else None
        auth_required = False

        if file_path and file_path.exists():
            try:
                content = file_path.read_text(errors="ignore")
                auth_required = _has_auth_pattern(content, auth_stack)
            except (OSError, UnicodeDecodeError):
                pass

        # Fallback: check if route has auth_required from AST (if the field exists)
        if not auth_required and hasattr(route, 'auth_required'):
            auth_required = route.auth_required

        normalized_path = _normalize_path(route.path)
        methods = route.methods if route.methods else ["GET"]
        line = route.line if hasattr(route, 'line') else 0
        fp = str(route.file) if hasattr(route, 'file') and route.file else ""

        entry = RouteIndexEntry(
            path=normalized_path,
            methods=methods,
            params={},
            auth_required=auth_required,
            auth_stack=auth_stack,
            file_path=fp,
            line=line,
        )
        entries.append(entry)

        # Flag sensitive routes without auth as info-level findings
        if not auth_required and _is_sensitive_route(normalized_path):
            logger.info(
                "route_mapper.open_api_surface",
                path=normalized_path,
                file=fp,
                auth_stack=auth_stack,
            )

    return entries


def build_index_from_repo(repo_path: str, stack: str, auth_stack: str = "custom") -> list[RouteIndexEntry]:
    """Convenience: parse repo then build route index in one call."""
    ast_result = parse_repo(repo_path, stack)
    return build_route_index(ast_result, stack, auth_stack)
