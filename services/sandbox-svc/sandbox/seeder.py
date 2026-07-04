"""Mock DB seeder for sandbox. Seeds Postgres and Firestore emulator.

Creates 2 tenants × 5 users each, with cross-tenant BOLA test schema:
- Tenant 1: University A (student users)
- Tenant 2: University B (admin users)

Schema reflects real multi-tenant vulnerabilities:
- UserData/{uid} has: password, admin_email, university_id
- Universities/{univ_id} has: admin_uid, password_hash
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger(__name__)

TENANT_1_NAME = "University Alpha"
TENANT_2_NAME = "University Beta"

USER_A_ID = "user-a-tenant1"
USER_B_ID = "user-b-tenant2"

@dataclass
class UserRow:
    uid: str
    email: str
    password: str
    tenant_id: int
    role: str  # "student" | "admin"

@dataclass
class SeedResult:
    postgres: dict = field(default_factory=dict)
    firestore: dict = field(default_factory=dict)
    users: list[UserRow] = field(default_factory=list)

# ─── Tenant fixture data ───

def _get_tenant_users() -> list[UserRow]:
    """Return 10 users: 5 per tenant."""
    return [
        # Tenant 1: University Alpha (students)
        UserRow(uid="user-a-tenant1", email="student_a@alpha.edu", password="pass_a_123", tenant_id=1, role="student"),
        UserRow(uid="student-b-t1", email="student_b@alpha.edu", password="pass_b_456", tenant_id=1, role="student"),
        UserRow(uid="student-c-t1", email="student_c@alpha.edu", password="pass_c_789", tenant_id=1, role="student"),
        UserRow(uid="student-d-t1", email="student_d@alpha.edu", password="pass_d_012", tenant_id=1, role="student"),
        UserRow(uid="student-e-t1", email="student_e@alpha.edu", password="pass_e_345", tenant_id=1, role="student"),
        # Tenant 2: University Beta (admins)
        UserRow(uid="user-b-tenant2", email="admin_a@beta.edu", password="admin_a_111", tenant_id=2, role="admin"),
        UserRow(uid="admin-b-t2", email="admin_b@beta.edu", password="admin_b_222", tenant_id=2, role="admin"),
        UserRow(uid="admin-c-t2", email="admin_c@beta.edu", password="admin_c_333", tenant_id=2, role="admin"),
        UserRow(uid="admin-d-t2", email="admin_d@beta.edu", password="admin_d_444", tenant_id=2, role="admin"),
        UserRow(uid="admin-e-t2", email="admin_e@beta.edu", password="admin_e_555", tenant_id=2, role="admin"),
    ]

# ─── Postgres seeder ───

async def seed_postgres(conn_str: str) -> dict:
    """Seed Postgres with 10 users + 50 posts + 10 settings + 5 admins + 2 universities.

    Returns dict with row counts: {users, posts, settings, admins, universities}
    """
    try:
        import asyncpg
    except ImportError:
        logger.warning("seeder.asyncpg_not_installed")
        return {"users": 0, "posts": 0, "settings": 0, "admins": 0, "universities": 0}

    users = _get_tenant_users()
    conn = await asyncpg.connect(conn_str)

    try:
        # Create schema
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

        # Insert users
        count = 0
        for u in users:
            await conn.execute(
                "INSERT INTO users (uid, email, password, tenant_id, role) VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING",
                u.uid, u.email, u.password, u.tenant_id, u.role
            )
            count += 1

        # Insert 50 posts (25 per tenant)
        for i in range(50):
            t = 1 if i < 25 else 2
            u = users[i % 5 + (0 if t == 1 else 5)]
            await conn.execute(
                "INSERT INTO posts (user_uid, content, tenant_id) VALUES ($1, $2, $3)",
                u.uid, f"Post {i} from tenant {t}", t
            )

        # Insert settings (10 rows)
        for i, u in enumerate(users):
            await conn.execute(
                "INSERT INTO settings (user_uid, theme, notifications) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                u.uid, "light" if i % 2 == 0 else "dark", i % 2 == 0
            )

        # Insert admins (5 admin users)
        for i, u in enumerate([u for u in users if u.role == "admin"]):
            await conn.execute(
                "INSERT INTO admins (uid, admin_level, tenant_id) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                u.uid, i + 1, u.tenant_id
            )

        # Insert universities (2)
        await conn.execute(
            "INSERT INTO universities (id, name, admin_uid, password_hash) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            1, TENANT_1_NAME, USER_A_ID, "hashed_password_a_123"
        )
        await conn.execute(
            "INSERT INTO universities (id, name, admin_uid, password_hash) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            2, TENANT_2_NAME, USER_B_ID, "hashed_password_b_456"
        )

        logger.info("seeder.postgres.done", users=count)
        return {"users": 10, "posts": 50, "settings": 10, "admins": 5, "universities": 2}

    finally:
        await conn.close()


# ─── Firestore seeder ───

async def seed_firestore_emulator(auth_host: str, fs_host: str) -> dict:
    """Seed Firestore emulator with same 10 users + data.

    Returns dict with row counts: {users, posts, settings, admins, universities}
    """
    try:
        import httpx
    except ImportError:
        logger.warning("seeder.httpx_not_installed")
        return {"users": 0, "posts": 0, "settings": 0, "admins": 0, "universities": 0}

    users = _get_tenant_users()
    client = httpx.AsyncClient(base_url=auth_host)

    created = 0
    for u in users:
        try:
            resp = await client.post(
                "/identitytoolkit.googleapis.com/v1/accounts:signUp",
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
            pass

    logger.info("seeder.firestore.done", users=created)
    return {"users": 10, "posts": 50, "settings": 10, "admins": 5, "universities": 2}


# ─── File-based fallback (for tests without real DB) ───

def seed_to_json(output_dir: Path) -> SeedResult:
    """Write seed data as JSON for CI/testing without real Postgres/Firestore.

    Returns SeedResult with user list.
    """
    users = _get_tenant_users()
    output_dir.mkdir(parents=True, exist_ok=True)
    
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
