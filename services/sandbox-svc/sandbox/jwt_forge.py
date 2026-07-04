"""JWT forge for sandbox. Mints auth tokens for 5 auth-stack adapters.

Adapters:
- nextauth: HS256 with NEXTAUTH_SECRET (fallback to random 32-char)
- clerk: RS256 with temp keypair, claims mimic Clerk session JWT
- firebase: custom token via firebase_admin SDK OR HS256 fallback if SDK missing
- supabase: HS256 JWT matching Supabase auth (sub, role, app_metadata, user_metadata)
- custom: HS256 with JWT_SECRET OR RS256 fallback with temp keypair

`forge()` returns (User_A token, User_B token) for cross-tenant BOLA testing.
"""

import time
import secrets
from dataclasses import dataclass, field
from typing import Callable, Optional
import structlog

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from sandbox.seeder import SeedResult, UserRow, USER_A_ID, USER_B_ID

logger = structlog.get_logger(__name__)

TOKEN_TTL_SECONDS = 3600  # 1h
RSA_KEY_SIZE = 2048


@dataclass
class ForgedToken:
    token: str
    user_id: str
    tenant_id: int
    role: str
    auth_stack: str
    claims: dict = field(default_factory=dict)


# ─── Helpers ───

def _now() -> int:
    return int(time.time())


def _random_secret(n: int = 32) -> str:
    """Fallback secret when env var missing. Cryptographically random."""
    return secrets.token_urlsafe(n)


def _generate_rsa_keypair() -> tuple[bytes, bytes]:
    """Generate temp RSA keypair. Returns (private_pem, public_pem)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=RSA_KEY_SIZE)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _base_claims(user: UserRow) -> dict:
    now = _now()
    return {
        "sub": user.uid,
        "email": user.email,
        "role": user.role,
        "tenant_id": user.tenant_id,
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
    }


def _wrap(user: UserRow, auth_stack: str, token: str, claims: dict) -> ForgedToken:
    return ForgedToken(
        token=token,
        user_id=user.uid,
        tenant_id=user.tenant_id,
        role=user.role,
        auth_stack=auth_stack,
        claims=claims,
    )


# ─── Adapters ───

def forge_nextauth(env: dict, user: UserRow) -> ForgedToken:
    """NextAuth: HS256 with NEXTAUTH_SECRET. Fallback to random 32-char secret."""
    secret = env.get("NEXTAUTH_SECRET") or _random_secret(32)
    claims = _base_claims(user)
    claims["name"] = user.email.split("@")[0]
    token = jwt.encode(claims, secret, algorithm="HS256")
    return _wrap(user, "nextauth", token, claims)


def forge_clerk(env: dict, user: UserRow) -> ForgedToken:
    """Clerk: RS256 with temp keypair. Mock Clerk session JWT shape."""
    private_pem, _ = _generate_rsa_keypair()
    now = _now()
    claims = {
        "sub": user.uid,
        "email": user.email,
        "role": user.role,
        "tenant_id": user.tenant_id,
        "clerk_user_id": f"user_{user.uid}",
        "org_id": f"org_tenant_{user.tenant_id}",
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
    }
    token = jwt.encode(claims, private_pem, algorithm="RS256")
    return _wrap(user, "clerk", token, claims)


def forge_firebase(env: dict, user: UserRow) -> ForgedToken:
    """Firebase: custom token via firebase_admin SDK. Fallback to HS256 if SDK unavailable."""
    try:
        import firebase_admin  # noqa: F401
        from firebase_admin import auth as fb_auth
        # Try to use SDK; if no app initialized, fallback
        try:
            token = fb_auth.create_custom_token(user.uid, {"tenant_id": user.tenant_id, "role": user.role}).decode("utf-8")
            claims = {
                "sub": user.uid,
                "email": user.email,
                "role": user.role,
                "tenant_id": user.tenant_id,
                "uid": user.uid,
                "claims": {"tenant_id": user.tenant_id, "role": user.role},
                "iat": _now(),
                "exp": _now() + TOKEN_TTL_SECONDS,
            }
            return _wrap(user, "firebase", token, claims)
        except Exception:
            pass
    except ImportError:
        logger.warning("jwt_forge.firebase_sdk_missing_fallback_hs256")

    # HS256 fallback (no real Firebase emulator / network)
    secret = env.get("FIREBASE_SECRET") or _random_secret(32)
    claims = _base_claims(user)
    claims["uid"] = user.uid
    claims["claims"] = {"tenant_id": user.tenant_id, "role": user.role}
    token = jwt.encode(claims, secret, algorithm="HS256")
    return _wrap(user, "firebase", token, claims)


def forge_supabase(env: dict, user: UserRow) -> ForgedToken:
    """Supabase: HS256 JWT matching Supabase auth format."""
    secret = env.get("SUPABASE_JWT_SECRET") or env.get("JWT_SECRET") or _random_secret(32)
    now = _now()
    claims = {
        "sub": user.uid,
        "email": user.email,
        "role": "authenticated",
        "app_metadata": {"tenant_id": user.tenant_id, "role": user.role},
        "user_metadata": {"email": user.email, "role": user.role},
        "tenant_id": user.tenant_id,
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
    }
    token = jwt.encode(claims, secret, algorithm="HS256")
    return _wrap(user, "supabase", token, claims)


def forge_custom(env: dict, user: UserRow) -> ForgedToken:
    """Custom: HS256 if JWT_SECRET present, else RS256 with temp keypair."""
    now = _now()
    claims = _base_claims(user)
    secret = env.get("JWT_SECRET")

    if secret:
        token = jwt.encode(claims, secret, algorithm="HS256")
    else:
        private_pem, _ = _generate_rsa_keypair()
        kid = f"temp-{user.tenant_id}-{user.uid[:8]}"
        token = jwt.encode(
            claims,
            private_pem,
            algorithm="RS256",
            headers={"kid": kid},
        )

    return _wrap(user, "custom", token, claims)


# ─── Adapter registry ───

ADAPTERS: dict[str, Callable[[dict, UserRow], ForgedToken]] = {
    "nextauth": forge_nextauth,
    "clerk": forge_clerk,
    "firebase": forge_firebase,
    "supabase": forge_supabase,
    "custom": forge_custom,
}


# ─── Public entry point ───

def _find_user(seed_result: SeedResult, uid: str) -> UserRow:
    for u in seed_result.users:
        if u.uid == uid:
            return u
    raise ValueError(f"User {uid} not found in seed_result")


def forge(env_root: dict, auth_stack: str, seed_result: SeedResult) -> tuple[ForgedToken, ForgedToken]:
    """Mint tokens for USER_A_ID and USER_B_ID using the given auth stack.

    Args:
        env_root: Sandbox env dict (NEXTAUTH_SECRET, JWT_SECRET, etc.)
        auth_stack: One of: nextauth, clerk, firebase, supabase, custom
        seed_result: From sandbox.seeder.seed_to_json()

    Returns:
        (User_A token, User_B token) for cross-tenant BOLA testing
    """
    if auth_stack not in ADAPTERS:
        raise ValueError(f"Unknown auth_stack: {auth_stack}. Valid: {list(ADAPTERS.keys())}")

    adapter = ADAPTERS[auth_stack]
    user_a = _find_user(seed_result, USER_A_ID)
    user_b = _find_user(seed_result, USER_B_ID)

    token_a = adapter(env_root, user_a)
    token_b = adapter(env_root, user_b)

    logger.info(
        "jwt_forge.done",
        auth_stack=auth_stack,
        user_a=user_a.uid,
        tenant_a=user_a.tenant_id,
        user_b=user_b.uid,
        tenant_b=user_b.tenant_id,
    )
    return token_a, token_b
