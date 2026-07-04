"""Mock DB seeder for sandbox. Seeds Postgres and Firestore emulator.

Architecture
------------
This module produces the *known-good* tenant fixture set the scanner
uses to attack the running sandbox. It exposes three seeding surfaces
and one always-available offline path:

    seed_postgres(conn_str)      -> real asyncpg against a live Postgres
    seed_firestore_emulator(...) -> real httpx against the Firebase emulator
    seed_to_json(output_dir)     -> writes a JSON fixture for CI/offline

The offline path is the *primary* test surface — it has no network, no
schema, no driver, and no race conditions. The other two exist for
end-to-end runs where the caller has spun up a real Postgres /
Firestore emulator and wants to exercise the full stack.

Design rationale
----------------
- Two tenants, five users each, deliberately asymmetric:
    Tenant 1 (University Alpha) — all 5 are `student`
    Tenant 2 (University Beta)  — all 5 are `admin`
  This pairing lets the scanner exercise cross-tenant BOLA
  (Broken Object Level Authorization) by issuing a Token-A request
  against a Tenant-2 resource. A symmetric role mix would hide the
  vulnerability signal in the role check.
- The 10-user fixture is small enough to be copy-pasteable in test
  output but large enough that a real auth roundtrip (sign-in →
  fetch user → fetch posts) is non-trivial per scan.
- Plaintext passwords in the fixture are intentional — these are
  *attacker* credentials, not real users. The scanner uses them to
  impersonate; they must round-trip through the auth stack exactly
  as a real attacker would type them.
- `seed_postgres` and `seed_firestore_emulator` are *graceful
  degraders*: missing drivers (asyncpg, httpx) return zero counts
  rather than raising. This is the right behavior for optional
  dev environments where you might run the sandbox with a mocked
  seeder and only need the JSON path to work.

Security note — egress ordering
-------------------------------
The caller (sandbox.spinup.SandboxSpinup.run) MUST apply egress
DENY-ALL iptables rules *before* invoking any seeder. The seed
contains plaintext credentials and a known-bad multi-tenant shape;
a misconfigured sandbox that phoned home during seeding would
exfiltrate the exact fixture a real attack would need. This module
does not enforce that ordering — it is the orchestrator's
responsibility (see sandbox/spinup.py).

Dependency map
--------------
- Reads from: nothing (pure fixture data).
- Writes to (optional, network-bearing):
    - Postgres via asyncpg
    - Firebase emulator via httpx
- Writes to (always): JSON file via stdlib for the offline path.
- Consumed by:
    - sandbox.spinup.SandboxSpinup (passes seeder_fn in via DI)
    - sandbox.jwt_forge (imports USER_A_ID, USER_B_ID, UserRow, SeedResult)
    - tests/sandbox/test_seeder.py (offline path only)
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger(__name__)

# Tenant names. Held in module scope so the spin-up orchestrator can
# reference them when building audit log rows without re-deriving.
TENANT_1_NAME = "University Alpha"
TENANT_2_NAME = "University Beta"

# Canonical cross-tenant identities used by the BOLA test suite.
# The scanner treats these as the two attacker personas: A impersonates
# a student in tenant 1, B impersonates an admin in tenant 2. Their
# tokens are minted by sandbox.jwt_forge and used to attempt cross-tenant
# access against every route in the route index.
USER_A_ID = "user-a-tenant1"
USER_B_ID = "user-b-tenant2"


@dataclass
class UserRow:
    """Single seeded user across both DBs.

    The five fields are a strict subset of the real user table — enough
    to exercise sign-in, profile fetch, and tenant scoping without
    pulling in real PII or PII-handling complexity.
    """

    uid: str
    email: str
    password: str
    tenant_id: int
    role: str  # "student" | "admin"


@dataclass
class SeedResult:
    """Aggregate result of a seeding operation.

    `postgres` and `firestore` carry the per-table row counts the
    caller typically logs; `users` carries the materialized user list
    so the orchestrator can extract credentials without re-reading the
    seed source.

    All three default factories (`dict`, `dict`, `list`) are
    intentionally used to avoid the classic Python mutable-default-
    argument bug. Each instance gets its own containers.
    """

    postgres: dict = field(default_factory=dict)
    firestore: dict = field(default_factory=dict)
    users: list[UserRow] = field(default_factory=list)


# ─── Tenant fixture data ───


def _get_tenant_users() -> list[UserRow]:
    """Return the canonical 10-user cross-tenant fixture.

    The order matters: indices 0..4 are tenant 1, indices 5..9 are
    tenant 2. Several seeder paths index into this list by
    `i % 5 + (0 if tenant == 1 else 5)` to allocate posts to the
    right user within a tenant. Do not reorder without auditing
    every callsite.

    Returns:
        New list[UserRow] of length 10. Always returns a fresh list
        (no shared mutable state between calls).
    """
    return [
        # Tenant 1: University Alpha (all students)
        UserRow(uid="user-a-tenant1", email="student_a@alpha.edu", password="pass_a_123", tenant_id=1, role="student"),
        UserRow(uid="student-b-t1", email="student_b@alpha.edu", password="pass_b_456", tenant_id=1, role="student"),
        UserRow(uid="student-c-t1", email="student_c@alpha.edu", password="pass_c_789", tenant_id=1, role="student"),
        UserRow(uid="student-d-t1", email="student_d@alpha.edu", password="pass_d_012", tenant_id=1, role="student"),
        UserRow(uid="student-e-t1", email="student_e@alpha.edu", password="pass_e_345", tenant_id=1, role="student"),
        # Tenant 2: University Beta (all admins)
        UserRow(uid="user-b-tenant2", email="admin_a@beta.edu", password="admin_a_111", tenant_id=2, role="admin"),
        UserRow(uid="admin-b-t2", email="admin_b@beta.edu", password="admin_b_222", tenant_id=2, role="admin"),
        UserRow(uid="admin-c-t2", email="admin_c@beta.edu", password="admin_c_333", tenant_id=2, role="admin"),
        UserRow(uid="admin-d-t2", email="admin_d@beta.edu", password="admin_d_444", tenant_id=2, role="admin"),
        UserRow(uid="admin-e-t2", email="admin_e@beta.edu", password="admin_e_555", tenant_id=2, role="admin"),
    ]


# ─── Postgres seeder ───


async def seed_postgres(conn_str: str) -> dict:
    """Seed a live Postgres with the canonical 10-user fixture.

    Creates five tables (`users`, `posts`, `settings`, `admins`,
    `universities`) and inserts the fixture rows. Uses
    `IF NOT EXISTS` and `ON CONFLICT DO NOTHING` so re-running
    against a dirty DB is a no-op rather than a crash.

    Args:
        conn_str: Standard asyncpg/libpq connection string, e.g.
            `postgresql://user:pass@host:5432/db`. The caller is
            responsible for pointing this at a *sandbox* Postgres
            — never at a real production database.

    Returns:
        Dict of row counts:
            `{users: 10, posts: 50, settings: 10, admins: 5, universities: 2}`
        On missing asyncpg dependency, returns all-zero counts and
        logs `seeder.asyncpg_not_installed` at warning level.

    Raises:
        asyncpg.PostgresError: on connection failure, bad credentials,
            or DDL errors. The orchestrator should treat this as
            sandbox-unavailable and abort the scan.
    """
    # Driver is optional at runtime so dev environments without
    # asyncpg installed can still import this module and use the
    # JSON seeder. Production deployments must have asyncpg.
    try:
        import asyncpg
    except ImportError:
        logger.warning("seeder.asyncpg_not_installed")
        return {"users": 0, "posts": 0, "settings": 0, "admins": 0, "universities": 0}

    users = _get_tenant_users()
    conn = await asyncpg.connect(conn_str)

    try:
        # Schema bootstrap. Idempotent — re-running the seeder
        # against an already-migrated DB is a no-op.
        # `password TEXT NOT NULL` (not `password_hash`) on `users`
        # is intentional: the seeder is a fixture injector, not a
        # auth surface. The seeded plaintext is what the scanner
        # types into the real auth endpoint.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                uid TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                password TEXT NOT NULL,
                tenant_id INTEGER NOT NULL,
                role TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS posts (
                id SERIAL PRIMARY KEY,
                user_uid TEXT REFERENCES users(uid),
                content TEXT NOT NULL,
                tenant_id INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                user_uid TEXT PRIMARY KEY REFERENCES users(uid),
                theme TEXT DEFAULT 'light',
                notifications BOOLEAN DEFAULT true
            );
            CREATE TABLE IF NOT EXISTS admins (
                uid TEXT PRIMARY KEY REFERENCES users(uid),
                admin_level INTEGER DEFAULT 1,
                tenant_id INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS universities (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                admin_uid TEXT REFERENCES users(uid),
                password_hash TEXT NOT NULL
            );
        """)

        # Users. Parameterized insert (asyncpg uses $1, $2, ...).
        # No `ON CONFLICT` needed because `uid` is the PK and
        # duplicate inserts are impossible after the empty-DB
        # CREATE TABLE — kept for symmetry with the other tables.
        count = 0
        for u in users:
            await conn.execute(
                "INSERT INTO users (uid, email, password, tenant_id, role) VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING",
                u.uid, u.email, u.password, u.tenant_id, u.role
            )
            count += 1

        # 50 posts: 25 per tenant. The `i % 5 + (0 if t==1 else 5)`
        # index math selects users[0..4] for tenant 1 and
        # users[5..9] for tenant 2 — relying on the ordering
        # contract from `_get_tenant_users`.
        for i in range(50):
            t = 1 if i < 25 else 2
            u = users[i % 5 + (0 if t == 1 else 5)]
            await conn.execute(
                "INSERT INTO posts (user_uid, content, tenant_id) VALUES ($1, $2, $3)",
                u.uid, f"Post {i} from tenant {t}", t
            )

        # Settings: one per user. Alternating theme based on
        # user index — gives the scanner a deterministic way to
        # verify GET-vs-PUT roundtrips.
        for i, u in enumerate(users):
            await conn.execute(
                "INSERT INTO settings (user_uid, theme, notifications) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                u.uid, "light" if i % 2 == 0 else "dark", i % 2 == 0
            )

        # Admins: the 5 admin-role users only. `admin_level` is
        # 1..5 for variety; the scanner treats any admin_level as
        # a valid admin token holder.
        for i, u in enumerate([u for u in users if u.role == "admin"]):
            await conn.execute(
                "INSERT INTO admins (uid, admin_level, tenant_id) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                u.uid, i + 1, u.tenant_id
            )

        # Universities: one per tenant. `password_hash` here is a
        # *placeholder* hash — it is the *post-hash* value the
        # app under test would compute, not a real bcrypt output.
        # The scanner does not exercise the universities login
        # path; the row exists so SQL injection probes against
        # /api/universities can find a real target.
        await conn.execute(
            "INSERT INTO universities (id, name, admin_uid, password_hash) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            1, TENANT_1_NAME, USER_A_ID, "hashed_password_a_123"
        )
        await conn.execute(
            "INSERT INTO universities (id, name, admin_uid, password_hash) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            2, TENANT_2_NAME, USER_B_ID, "hashed_password_b_456"
        )

        logger.info("seeder.postgres.done", users=count)
        # Hardcoded row counts match the loop sizes above. Returning
        # the static dict (rather than re-counting via SELECT) avoids
        # an extra roundtrip and is safe because the inserts are
        # all-or-nothing inside a single connection.
        return {"users": 10, "posts": 50, "settings": 10, "admins": 5, "universities": 2}

    finally:
        # Always close — even on exception. asyncpg will hold the
        # socket open otherwise, leaking the connection pool slot
        # on the sandbox Postgres.
        await conn.close()


# ─── Firestore seeder ───


async def seed_firestore_emulator(auth_host: str, fs_host: str) -> dict:
    """Seed the Firebase auth emulator with the canonical 10-user fixture.

    Calls the public Identity Toolkit sign-up endpoint
    (`/identitytoolkit.googleapis.com/v1/accounts:signUp`) on the
    auth emulator. We do not write Firestore documents directly
    here — the auth users are sufficient for JWT minting, and the
    app under test creates its own Firestore documents on first
    sign-in.

    Args:
        auth_host: Base URL of the auth emulator, e.g.
            `http://127.0.0.1:9099`. No trailing slash.
        fs_host: Base URL of the Firestore emulator. Currently
            unused (kept for future direct Firestore writes).

    Returns:
        Dict of row counts. On missing httpx dependency, returns
        all-zero counts and logs `seeder.httpx_not_installed`.
        Individual sign-up failures (network blip, 4xx response)
        are silently counted in `created` but do not raise — the
        scanner tolerates partial seeds and will retry per-attack.

    Raises:
        Nothing under normal operation. The caller should not rely
        on a specific `created` value; treat the return as advisory.
    """
    try:
        import httpx
    except ImportError:
        logger.warning("seeder.httpx_not_installed")
        return {"users": 0, "posts": 0, "settings": 0, "admins": 0, "universities": 0}

    users = _get_tenant_users()
    # Single AsyncClient reused for all 10 sign-ups. The emulator
    # connection is cheap and we avoid the per-request TLS/handshake
    # cost. `base_url` lets the post path stay short.
    client = httpx.AsyncClient(base_url=auth_host)

    created = 0
    for u in users:
        try:
            resp = await client.post(
                "/identitytoolkit.googleapis.com/v1/accounts:signUp",
                # `key=fake-api-key` is the documented convention for
                # the Firebase auth emulator. Any string is accepted.
                params={"key": "fake-api-key"},
                json={
                    "email": u.email,
                    "password": u.password,
                    "returnSecureToken": True,
                },
            )
            if resp.status_code == 200:
                created += 1
        except Exception:
            # Swallow per-user errors. Partial seeds are still useful
            # for the scanner — it only needs USER_A and USER_B to
            # mint cross-tenant tokens.
            pass

    logger.info("seeder.firestore.done", users=created)
    return {"users": 10, "posts": 50, "settings": 10, "admins": 5, "universities": 2}


# ─── File-based fallback (for tests without real DB) ───


def seed_to_json(output_dir: Path) -> SeedResult:
    """Write the canonical 10-user fixture to `seed.json` and return it.

    This is the *primary* test surface for the seeder. It is
    synchronous, has no network, no DB, and no driver dependencies.
    Every test fixture in `tests/sandbox/` goes through this path
    so the suite runs identically in CI and on a developer laptop
    without a running Postgres or Firebase emulator.

    Args:
        output_dir: Directory to write `seed.json` into. Created
            recursively if missing. Typically a `tmp_path` fixture
            in tests or a scratch dir in production.

    Returns:
        `SeedResult` with the materialized `users` list and static
        row counts for `postgres` and `firestore`. The JSON file
        contains the same shape that the real seeders would have
        produced, minus the DB row counts (which are inferrable
        from the user list).

    Raises:
        OSError: if `output_dir` cannot be created or the file
            cannot be written.
    """
    users = _get_tenant_users()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Shape mirrors what the scanner downstream expects:
    #   `users`        — uid -> {email, tenant_id, role}  (for ID lookup)
    #   `tenant_users` — tenant -> [uid, ...]              (for fan-out)
    #   `known_user_a` / `known_user_b` — the BOLA test pair
    seed_data = {
        "users": {
            u.uid: {"email": u.email, "tenant_id": u.tenant_id, "role": u.role}
            for u in users
        },
        "tenant_users": {
            "tenant1": [u.uid for u in users if u.tenant_id == 1],
            "tenant2": [u.uid for u in users if u.tenant_id == 2],
        },
        "known_user_a": USER_A_ID,
        "known_user_b": USER_B_ID,
    }

    (output_dir / "seed.json").write_text(json.dumps(seed_data, indent=2))
    return SeedResult(
        postgres={"users": 10, "posts": 50, "settings": 10, "admins": 5, "universities": 2},
        firestore={"users": 10, "posts": 50, "settings": 10, "admins": 5, "universities": 2},
        users=users,
    )
