"""Tests for sandbox JWT forge.

Verifies:
- nextauth forges HS256 with correct claims
- custom HS256 path uses JWT_SECRET
- custom RS256 fallback works when JWT_SECRET missing
- both tenants have correct tenant_id (1, 2)
- exp claim ~3600s from now (±10s)
- clerk forges valid token format
- no real network calls / emulators
"""

import time
import tempfile
from pathlib import Path

import jwt
import pytest

from sandbox.seeder import seed_to_json, USER_A_ID, USER_B_ID
from sandbox.jwt_forge import (
    ADAPTERS,
    ForgedToken,
    forge,
    forge_nextauth,
    forge_clerk,
    forge_firebase,
    forge_supabase,
    forge_custom,
    _generate_rsa_keypair,
    TOKEN_TTL_SECONDS,
)


@pytest.fixture
def seed_result(tmp_path: Path):
    """Seed to a tempdir; returns SeedResult with USER_A + USER_B present."""
    return seed_to_json(tmp_path)


@pytest.fixture
def env_with_nextauth() -> dict:
    return {"NEXTAUTH_SECRET": "test-nextauth-secret-32chars-1234"}


@pytest.fixture
def env_with_jwt_secret() -> dict:
    return {"JWT_SECRET": "test-jwt-secret-32chars-5678"}


# ─── Registry / structure ───

class TestAdapterRegistry:
    def test_all_5_adapters_registered(self):
        assert set(ADAPTERS.keys()) == {"nextauth", "clerk", "firebase", "supabase", "custom"}

    def test_adapters_callable(self):
        for name, fn in ADAPTERS.items():
            assert callable(fn), f"{name} not callable"


# ─── NextAuth (HS256) ───

class TestNextAuthForge:
    def test_token_decodes_with_secret(self, env_with_nextauth, seed_result):
        user_a = next(u for u in seed_result.users if u.uid == USER_A_ID)
        forged = forge_nextauth(env_with_nextauth, user_a)

        # Decode with the same secret
        decoded = jwt.decode(forged.token, env_with_nextauth["NEXTAUTH_SECRET"], algorithms=["HS256"])
        assert decoded["sub"] == USER_A_ID
        assert decoded["tenant_id"] == 1
        assert decoded["role"] == "student"
        assert "exp" in decoded
        assert "iat" in decoded

    def test_token_has_required_claims(self, env_with_nextauth, seed_result):
        user_a = next(u for u in seed_result.users if u.uid == USER_A_ID)
        forged = forge_nextauth(env_with_nextauth, user_a)
        assert forged.auth_stack == "nextauth"
        assert forged.user_id == USER_A_ID
        assert forged.tenant_id == 1
        assert forged.role == "student"
        for claim in ("sub", "email", "role", "tenant_id", "iat", "exp"):
            assert claim in forged.claims, f"missing {claim}"

    def test_fallback_secret_when_missing(self, seed_result):
        user_a = next(u for u in seed_result.users if u.uid == USER_A_ID)
        # Empty env → should still produce a valid token (random secret fallback)
        forged = forge_nextauth({}, user_a)
        assert isinstance(forged.token, str)
        assert len(forged.token.split(".")) == 3  # valid JWT shape


# ─── Custom (HS256 + RS256 fallback) ───

class TestCustomHS256:
    def test_hs256_when_jwt_secret_present(self, env_with_jwt_secret, seed_result):
        user_a = next(u for u in seed_result.users if u.uid == USER_A_ID)
        forged = forge_custom(env_with_jwt_secret, user_a)

        # Should be HS256
        header = jwt.get_unverified_header(forged.token)
        assert header["alg"] == "HS256"

        # Decode with the same secret
        decoded = jwt.decode(forged.token, env_with_jwt_secret["JWT_SECRET"], algorithms=["HS256"])
        assert decoded["sub"] == USER_A_ID
        assert decoded["tenant_id"] == 1
        assert decoded["role"] == "student"
        assert decoded["email"] == "student_a@alpha.edu"


class TestCustomRS256Fallback:
    def test_rs256_when_jwt_secret_missing(self, seed_result):
        user_a = next(u for u in seed_result.users if u.uid == USER_A_ID)
        # No JWT_SECRET → RS256 fallback
        forged = forge_custom({}, user_a)

        header = jwt.get_unverified_header(forged.token)
        assert header["alg"] == "RS256"
        # kid should be present in fallback (matches our impl)
        assert "kid" in header

        # Claims still present
        assert forged.claims["sub"] == USER_A_ID
        assert forged.claims["tenant_id"] == 1
        assert forged.claims["role"] == "student"


# ─── Cross-tenant fixture (BOLA testing) ───

class TestBothTenants:
    def test_user_a_tenant_1(self, env_with_nextauth, seed_result):
        token_a, _ = forge(env_with_nextauth, "nextauth", seed_result)
        assert token_a.tenant_id == 1
        assert token_a.user_id == USER_A_ID
        assert token_a.role == "student"

    def test_user_b_tenant_2(self, env_with_nextauth, seed_result):
        _, token_b = forge(env_with_nextauth, "nextauth", seed_result)
        assert token_b.tenant_id == 2
        assert token_b.user_id == USER_B_ID
        assert token_b.role == "admin"

    def test_cross_tenant_user_ids_present(self, env_with_nextauth, seed_result):
        token_a, token_b = forge(env_with_nextauth, "nextauth", seed_result)
        # Both tokens must exist and be different
        assert token_a.token != token_b.token
        # Cross-tenant ID test: USER_A_ID and USER_B_ID differ
        assert token_a.user_id == "user-a-tenant1"
        assert token_b.user_id == "user-b-tenant2"

    def test_all_5_stacks_mint_both_tenants(self, env_with_nextauth, seed_result):
        for stack in ("nextauth", "clerk", "firebase", "supabase", "custom"):
            token_a, token_b = forge(env_with_nextauth, stack, seed_result)
            assert token_a.tenant_id == 1, f"{stack}: user_a tenant wrong"
            assert token_b.tenant_id == 2, f"{stack}: user_b tenant wrong"
            assert token_a.auth_stack == stack
            assert token_b.auth_stack == stack


# ─── Expiration ───

class TestExpirationClaim:
    def test_exp_3600_seconds_from_now(self, env_with_nextauth, seed_result):
        user_a = next(u for u in seed_result.users if u.uid == USER_A_ID)
        before = int(time.time())
        forged = forge_nextauth(env_with_nextauth, user_a)
        after = int(time.time())

        exp = forged.claims["exp"]
        iat = forged.claims["iat"]
        # exp - iat should be exactly TOKEN_TTL_SECONDS
        assert exp - iat == TOKEN_TTL_SECONDS
        # iat should be within test execution window
        assert before <= iat <= after

    def test_exp_within_tolerance(self, env_with_nextauth, seed_result):
        """exp should be ~3600s from now (±10s tolerance)."""
        user_a = next(u for u in seed_result.users if u.uid == USER_A_ID)
        before = int(time.time())
        forged = forge_nextauth(env_with_nextauth, user_a)
        after = int(time.time())

        # The exp claim should land within [before+3590, after+3610] window
        assert before + TOKEN_TTL_SECONDS - 10 <= forged.claims["exp"] <= after + TOKEN_TTL_SECONDS + 10


# ─── Clerk (RS256) ───

class TestClerkFallback:
    def test_clerk_token_format_valid(self, seed_result):
        user_a = next(u for u in seed_result.users if u.uid == USER_A_ID)
        forged = forge_clerk({}, user_a)

        # Must be a valid JWT (3 parts)
        assert len(forged.token.split(".")) == 3
        # Algorithm is RS256
        header = jwt.get_unverified_header(forged.token)
        assert header["alg"] == "RS256"

    def test_clerk_contains_org_id_and_clerk_user_id(self, seed_result):
        user_a = next(u for u in seed_result.users if u.uid == USER_A_ID)
        forged = forge_clerk({}, user_a)
        assert forged.claims["org_id"] == "org_tenant_1"
        assert forged.claims["clerk_user_id"] == f"user_{user_a.uid}"
        assert forged.claims["tenant_id"] == 1


# ─── Firebase (HS256 fallback path) ───

class TestFirebaseFallback:
    def test_firebase_falls_back_to_hs256(self, seed_result):
        """firebase_admin not installed → HS256 fallback."""
        user_a = next(u for u in seed_result.users if u.uid == USER_A_ID)
        forged = forge_firebase({}, user_a)
        assert forged.auth_stack == "firebase"
        # Should be a valid 3-part JWT
        assert len(forged.token.split(".")) == 3
        assert forged.claims["uid"] == user_a.uid
        assert forged.claims["tenant_id"] == 1


# ─── Supabase ───

class TestSupabase:
    def test_supabase_token_has_supabase_claims(self, seed_result):
        user_a = next(u for u in seed_result.users if u.uid == USER_A_ID)
        forged = forge_supabase({}, user_a)
        assert forged.auth_stack == "supabase"
        assert forged.claims["sub"] == user_a.uid
        assert forged.claims["role"] == "authenticated"
        assert "app_metadata" in forged.claims
        assert "user_metadata" in forged.claims
        assert forged.claims["app_metadata"]["tenant_id"] == 1
        assert forged.claims["app_metadata"]["role"] == "student"


# ─── No network / no emulators (smoke test) ───

class TestNoNetworkCalls:
    def test_all_adapters_run_offline(self, seed_result):
        """All 5 adapters must complete with empty env (no network, no emulator)."""
        for stack in ("nextauth", "clerk", "firebase", "supabase", "custom"):
            forged_a, forged_b = forge({}, stack, seed_result)
            assert isinstance(forged_a, ForgedToken)
            assert isinstance(forged_b, ForgedToken)
            assert len(forged_a.token.split(".")) == 3
            assert len(forged_b.token.split(".")) == 3
