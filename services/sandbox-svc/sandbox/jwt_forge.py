"""JWT forge for sandbox. Mints auth tokens for 5 auth-stack adapters.

Architecture
------------
This module is the *only* place that knows how to mint a valid
auth token for each of the 5 supported auth libraries. The shape
of each token (claims, algorithm, signing key source) is
deliberately different per stack because that is exactly what
each library verifies on the receiving end — NextAuth expects
HS256 + NEXTAUTH_SECRET, Clerk expects RS256 with its key
header, etc. Converging on a single shape would be a lie the
auth libraries would catch on the first verify().

Adapters
--------
- nextauth : HS256, secret from `NEXTAUTH_SECRET` env (random
            32-char fallback so empty-env runs still produce a
            valid 3-part JWT).
- clerk    : RS256 with a per-call ephemeral keypair. Claims
            include `clerk_user_id` and `org_id` to mimic Clerk
            session JWT shape.
- firebase : Tries the `firebase_admin` SDK first; falls back to
            HS256 with `FIREBASE_SECRET` (or random) when the
            SDK is absent. This is the *only* adapter where the
            algorithm depends on the runtime environment.
- supabase : HS256 matching Supabase's `sub`/`role`/`app_metadata`/
            `user_metadata` claim set. Secret pulled from
            `SUPABASE_JWT_SECRET` or `JWT_SECRET` (or random).
- custom   : HS256 if `JWT_SECRET` is set, otherwise RS256 with
            an ephemeral keypair (kid header included). The
            RS256 branch is the production default — most
            modern stacks prefer RS256 with a rotating key.

Security notes
--------------
- All signing keys (HS256 secret, RS256 private key) are
  generated *per call* when the environment does not provide
  them. There is no key cache, no key persistence, and no key
  reuse across sandboxes. This is intentional: a leaked token
  from one sandbox must not be valid for any other.
- The random secret uses `secrets.token_urlsafe` (CSPRNG), not
  `random.choice`. The HS256 fallback is treated as a security-
  relevant key, not a session ID.
- `TOKEN_TTL_SECONDS = 3600` is the lifetime of every minted
  token. The scanner's full attack run is sub-minute; one hour
  gives generous headroom for retries without leaving a
  long-lived credential in the audit log.

Design rationale
----------------
- `forge()` returns `(User_A token, User_B token)` — exactly
  two tokens, not a list, because the BOLA test fixture has
  exactly two cross-tenant personas. Returning a list would
  invite callers to write `tokens[0]` indexing code that
  breaks the moment the fixture gains a third user.
- `_find_user` is the single point of failure when a tenant
  user is missing — it raises `ValueError` with a clear
  message, not `KeyError`. The orchestrator should treat
  this as a fixture bug, not a transient network error.
- Each adapter is independently callable. `forge()` is just
  sugar for "run the adapter twice, once for each tenant".
  This split lets tests target a single adapter and pass
  custom env dicts without going through the registry.

Dependency map
--------------
- Reads from: `sandbox.seeder` (USER_A_ID, USER_B_ID, UserRow,
              SeedResult).
- External libs: `pyjwt` (signing), `cryptography` (RS256
              keypair generation), `firebase_admin` (optional).
- Consumed by: the scanner's auth-bypass stage.

Testing
-------
- `tests/sandbox/test_jwt_forge.py` covers: every adapter,
  HS256/RS256 branches, exp-claim tolerance, claim shape per
  stack, both-tenant mint, fallback secret behavior, no-network
  smoke test. No real Firebase emulator is touched.
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

# Token lifetime in seconds. 1h is the right balance for a
# scanner run (sub-minute) vs. log retention (we want old
# tokens to expire so the audit log is self-cleaning).
TOKEN_TTL_SECONDS = 3600  # 1h

# RSA key size for the RS256 fallback branches. 2048 is the
# current OWASP minimum for new deployments (3072 is preferred
# for forward secrecy, but 2048 keeps the ephemeral keypair
# generation under ~50ms on a warm CPU).
RSA_KEY_SIZE = 2048


@dataclass
class ForgedToken:
    """A single minted token plus its identifying metadata.

    Carries the raw token string *and* the structured fields the
    scanner needs to log which user / tenant / role / stack
    generated it, without re-decoding the JWT (which would
    require the matching key in the audit logger too).

    Fields:
        token:       The compact-serialized JWT string.
        user_id:     The seeded `uid` the token was minted for.
        tenant_id:   1 or 2 — the cross-tenant pivot for BOLA.
        role:        "student" or "admin" — for role-aware attacks.
        auth_stack:  One of nextauth|clerk|firebase|supabase|custom.
        claims:      The claim dict that was signed. Stored for
                     audit / inspection; not used for verification.
    """

    token: str
    user_id: str
    tenant_id: int
    role: str
    auth_stack: str
    claims: dict = field(default_factory=dict)


# ─── Helpers ───


def _now() -> int:
    """Unix epoch seconds, integer-truncated for JWT `iat`/`exp`.

    JWT spec (RFC 7519 §2 / §4.1.4 / §4.1.6) requires `iat` and
    `exp` to be NumericDate — a JSON number of seconds since
    epoch. Truncation to int is the conventional choice; the
    alternative (float) is technically valid but not all verifiers
    accept it.
    """
    return int(time.time())


def _random_secret(n: int = 32) -> str:
    """Fallback HS256 secret when the env var is missing.

    Uses `secrets.token_urlsafe` which reads from the OS CSPRNG
    (`/dev/urandom` on Linux, `BCryptGenRandom` on Windows).
    NOT `random.choice` — that PRNG is seedable and would
    be a security bug in this context.

    Args:
        n: Number of random bytes. Default 32 → 43-char urlsafe
            string (base64 without padding). PyJWT requires the
            HMAC key to be at least 32 bytes for HS256 per
            RFC 7518 §3.2; the default enforces that floor.
    """
    return secrets.token_urlsafe(n)


def _generate_rsa_keypair() -> tuple[bytes, bytes]:
    """Generate an ephemeral RSA keypair for RS256 token signing.

    Returns:
        (private_pem, public_pem) as bytes. The private key
        is in PKCS8 PEM, unencrypted. The public key is in
        SubjectPublicKeyInfo PEM. The caller (the RS256
        adapters) uses only the private key for signing; the
        public key is returned for symmetry with future
        verification paths but is currently unused.

    Performance: 2048-bit RSA generation is ~30-50ms on a
    warm CPU. Acceptable for the per-scan call rate (1-2 keypairs
    per minute). If throughput ever becomes a concern, switch
    to `rsa.generate_private_key(public_exponent=65537, key_size=2048)`
    with a cached keypair behind a lock — but only after measuring.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=RSA_KEY_SIZE)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        # PKCS8 is the modern, algorithm-agnostic format. PKCS1
        # is RSA-specific and would couple this helper to RSA.
        format=serialization.PrivateFormat.PKCS8,
        # NoEncryption is correct for ephemeral keys — they live
        # only for the duration of the scan. A password here would
        # require a passphrase to be passed through the entire
        # adapter chain, with no security benefit.
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _base_claims(user: UserRow) -> dict:
    """Build the standard claim set every adapter starts from.

    Includes:
        sub, email, role, tenant_id — the four fields the scanner
            logs against every request.
        iat, exp — issued-at and expiry, both integer seconds.
            `exp = iat + TOKEN_TTL_SECONDS` (1h).

    Per-adapter extensions (name, clerk_user_id, org_id,
    app_metadata, user_metadata, etc.) are layered on by the
    adapter itself.
    """
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
    """Adapter output → ForgedToken.

    Centralized so every adapter returns the same shape, and so
    future fields (e.g. `issued_to_tenant`, `scanner_run_id`)
    can be added in one place.
    """
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
    """NextAuth adapter — HS256 with NEXTAUTH_SECRET.

    The `name` claim is the email local-part (the part before
    `@`). NextAuth's default `session.user.name` callback reads
    this field; the scanner needs it to be present and
    non-empty to test the `name` claim path.

    Args:
        env: Sandbox env dict. Reads `NEXTAUTH_SECRET`. Missing
            → `_random_secret(32)` fallback so empty-env tests
            still produce a valid 3-part JWT.
        user: Seeded user row.

    Returns:
        ForgedToken with `auth_stack="nextauth"`.
    """
    secret = env.get("NEXTAUTH_SECRET") or _random_secret(32)
    claims = _base_claims(user)
    claims["name"] = user.email.split("@")[0]
    token = jwt.encode(claims, secret, algorithm="HS256")
    return _wrap(user, "nextauth", token, claims)


def forge_clerk(env: dict, user: UserRow) -> ForgedToken:
    """Clerk adapter — RS256 with ephemeral keypair.

    Clerk's session JWTs are RS256 with the public key published
    in a JWKS endpoint. We cannot reach a real JWKS from a
    sandbox, so we sign with a per-call ephemeral keypair and
    rely on the Clerk middleware accepting the locally-published
    key (or skipping signature verification in the test app).

    The `clerk_user_id` and `org_id` claims are the two Clerk-
    specific fields. `clerk_user_id` follows Clerk's `user_<id>`
    convention; `org_id` uses `org_tenant_<n>` so the multi-tenant
    shape is visible in the claims.

    Args:
        env: Unused. Clerk's key is always ephemeral here.
        user: Seeded user row.

    Returns:
        ForgedToken with `auth_stack="clerk"`.
    """
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
    """Firebase adapter — firebase_admin SDK with HS256 fallback.

    Two-tier resolution:
        1. If `firebase_admin` is importable and an app is
           initialized, mint a real custom token via
           `firebase_admin.auth.create_custom_token`.
        2. Otherwise, fall back to HS256 with the secret from
           `FIREBASE_SECRET` (or random). This is the common
           path in CI where the firebase_admin SDK is heavy
           and adds startup time.

    The fallback is a *correct* HS256 JWT that satisfies any
    test app verifying the Firebase ID token shape with a
    shared HS256 secret. It is not interoperable with the real
    Firebase verifier (which would need an RS256 key), but the
    sandbox test apps are configured for the sandbox flow, not
    production Firebase.

    Args:
        env: Sandbox env dict. Reads `FIREBASE_SECRET` (fallback
            path only).
        user: Seeded user row.

    Returns:
        ForgedToken with `auth_stack="firebase"`. `claims` may
        have slightly different keys depending on which tier
        served the request — both include `tenant_id` and `role`.
    """
    try:
        import firebase_admin  # noqa: F401
        from firebase_admin import auth as fb_auth
        # Inner try: the SDK may be importable but no app
        # initialized, in which case create_custom_token raises
        # `ValueError: No Firebase app has been initialized`.
        # We treat that as "fall back to HS256" rather than
        # crash, because the orchestrator may not have called
        # `firebase_admin.initialize_app` in this run.
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
            # SDK available but no app initialized. Fall through
            # to HS256 below.
            pass
    except ImportError:
        # SDK not installed. Common in dev/test envs; we log
        # at warning so the operator can decide whether to
        # install the SDK for stricter token realism.
        logger.warning("jwt_forge.firebase_sdk_missing_fallback_hs256")

    # HS256 fallback path. Secret lookup: FIREBASE_SECRET env
    # (what the test app reads), then random.
    secret = env.get("FIREBASE_SECRET") or _random_secret(32)
    claims = _base_claims(user)
    claims["uid"] = user.uid
    # `claims` (nested) is the Firebase-Admin custom-token
    # shape — preserved here so a test app that does the
    # firebase-admin verification path still finds the field.
    claims["claims"] = {"tenant_id": user.tenant_id, "role": user.role}
    token = jwt.encode(claims, secret, algorithm="HS256")
    return _wrap(user, "firebase", token, claims)


def forge_supabase(env: dict, user: UserRow) -> ForgedToken:
    """Supabase adapter — HS256 matching the Supabase auth claim set.

    Supabase's JWT verifier expects:
        sub             — user UID
        role            — "authenticated" | "anon" | "service_role"
        app_metadata    — server-controlled claims (tenant_id, role)
        user_metadata   — user-controlled claims (email, role)

    `role = "authenticated"` is the constant Supabase uses for
    signed-in users; using the user's seeded role here would
    confuse the row-level security policies.

    Secret resolution order: `SUPABASE_JWT_SECRET` →
    `JWT_SECRET` → random. The two env var names are both
    accepted because Supabase deployments vary on which they
    configure; falling back to the generic `JWT_SECRET` is a
    common pattern in monorepos.

    Args:
        env: Sandbox env dict.
        user: Seeded user row.

    Returns:
        ForgedToken with `auth_stack="supabase"`.
    """
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
    """Custom adapter — HS256 if JWT_SECRET present, else RS256.

    The two-branch logic is the most complex in the file. It
    exists because custom auth stacks in the wild span both
    algorithm choices: the "express + jsonwebtoken" tutorial
    uses HS256, the "node + passport-jwt + JWKS" pattern uses
    RS256. We default to whichever the env var presence
    suggests, and produce a valid token in either case.

    RS256 branch:
        - Ephemeral keypair (see `_generate_rsa_keypair`).
        - `kid` header set to `temp-<tenant>-<uid8>` so the
          receiver can match it against a (mock) JWKS without
          ambiguity. The "temp-" prefix signals this is not a
          real persistent key.

    Args:
        env: Sandbox env dict. Reads `JWT_SECRET`.
        user: Seeded user row.

    Returns:
        ForgedToken with `auth_stack="custom"`. The algorithm
        is recoverable from the token's header (`jwt.get_unverified_header`).
    """
    now = _now()
    claims = _base_claims(user)
    secret = env.get("JWT_SECRET")

    if secret:
        # HS256 path. PyJWT enforces a 32-byte minimum for
        # HS256; a shorter secret will raise `InsecureKeyLength`
        # which is intentional — we want the dev to fix the
        # env var, not have the scanner silently sign with
        # a weak key.
        token = jwt.encode(claims, secret, algorithm="HS256")
    else:
        # RS256 fallback. Generate keypair per call so two
        # simultaneous sandboxes don't share a signing key.
        private_pem, _ = _generate_rsa_keypair()
        # `kid` (Key ID) header is the standard signal for
        # "look me up in the JWKS". The composite value gives
        # the receiver a unique key per (tenant, user) pair
        # without needing a centralized key registry.
        kid = f"temp-{user.tenant_id}-{user.uid[:8]}"
        token = jwt.encode(
            claims,
            private_pem,
            algorithm="RS256",
            headers={"kid": kid},
        )

    return _wrap(user, "custom", token, claims)


# ─── Adapter registry ───


# String key -> adapter function. Lookup is by exact name; an
# unknown name raises ValueError in `forge()` below. Adding a
# new stack means: write an adapter, add a key here.
ADAPTERS: dict[str, Callable[[dict, UserRow], ForgedToken]] = {
    "nextauth": forge_nextauth,
    "clerk": forge_clerk,
    "firebase": forge_firebase,
    "supabase": forge_supabase,
    "custom": forge_custom,
}


# ─── Public entry point ───


def _find_user(seed_result: SeedResult, uid: str) -> UserRow:
    """Linear scan for a seeded user by UID.

    O(n) over the 10-user fixture — fine for a sandbox-only
    module. A dict lookup would be a premature optimization.

    Args:
        seed_result: From `sandbox.seeder.seed_to_json` or
            equivalent.
        uid: The user UID to find (e.g. `USER_A_ID`).

    Returns:
        The matching `UserRow`.

    Raises:
        ValueError: if no user with the given UID exists in
            `seed_result.users`. The orchestrator should treat
            this as a fixture bug — both USER_A_ID and
            USER_B_ID are guaranteed to be present in
            `seed_to_json` output.
    """
    for u in seed_result.users:
        if u.uid == uid:
            return u
    raise ValueError(f"User {uid} not found in seed_result")


def forge(env_root: dict, auth_stack: str, seed_result: SeedResult) -> tuple[ForgedToken, ForgedToken]:
    """Mint tokens for USER_A and USER_B using the given auth stack.

    This is the orchestrator-facing entry point. It is the only
    function the scanner needs to call; everything else is
    internal adapter machinery.

    Args:
        env_root: Sandbox env dict. Passed straight through to
            the adapter; the adapter decides which keys to read.
        auth_stack: One of `"nextauth"`, `"clerk"`, `"firebase"`,
            `"supabase"`, `"custom"`. Exact match against
            `ADAPTERS`.
        seed_result: From `sandbox.seeder.seed_to_json()`. Must
            contain both `USER_A_ID` and `USER_B_ID` in
            `seed_result.users`.

    Returns:
        `(token_a, token_b)` — User_A's token first, User_B's
        second. Order is load-bearing: the scanner's BOLA tests
        expect the cross-tenant pair in this order.

    Raises:
        ValueError: if `auth_stack` is not in `ADAPTERS`, or
            if either tenant user is missing from `seed_result`.
            Both are fixture / config bugs, not transient errors.
    """
    if auth_stack not in ADAPTERS:
        raise ValueError(f"Unknown auth_stack: {auth_stack}. Valid: {list(ADAPTERS.keys())}")

    adapter = ADAPTERS[auth_stack]
    # Both lookups can raise if the seed is incomplete; that's
    # the right failure mode (fail loud on fixture bugs).
    user_a = _find_user(seed_result, USER_A_ID)
    user_b = _find_user(seed_result, USER_B_ID)

    token_a = adapter(env_root, user_a)
    token_b = adapter(env_root, user_b)

    # Audit-friendly log line. Includes both tenant IDs so
    # the SOC can correlate the cross-tenant pair without
    # re-decoding the tokens.
    logger.info(
        "jwt_forge.done",
        auth_stack=auth_stack,
        user_a=user_a.uid,
        tenant_a=user_a.tenant_id,
        user_b=user_b.uid,
        tenant_b=user_b.tenant_id,
    )
    return token_a, token_b
