# Feature: Mock DB Seeder

**Purpose:** Seed Postgres / Firestore emulator inside sandbox Machine w/ 10 fake users across 2 tenants (User_A student tenant1, User_B admin tenant2).
**Wave:** 3  **Owner task:** 17  **Status:** pending

## Public API
```python
class MockDBSeeder:
    async def seed_postgres(self, conn_str: str) -> dict[str, list[UserRow]]:
        """Returns {users, posts, settings, admins, universities}."""
    async def seed_firestore_emulator(self, *, auth_host: str, fs_host: str) -> dict[str, list[UserRow]]: ...
```

## Internal flow
1. **Postgres path**: connect via `asyncpg`; create minimal schema (`users`, `posts`, `settings`, `admins`, `universities`); insert 10 fake users (5 per tenant)
2. **Firestore path**: use `firebase-admin` Python client against emulator endpoints; pre-seed 10 users via Auth emulator REST `/identitytoolkit.googleapis.com/v1/accounts:signUp`; pre-seed `UserData/{uid}` (w/ `password`, `admin_email`, `university_id`); `Universities/{univ_id}` (w/ `admin_uid`, `password_hash`)
3. Schema design reflects cross-tenant BOLA test (one user can attempt to read other tenant's user) per system-design.md

## Inputs
- conn_str OR emulator host ports (localhost only)

## Outputs
- Dict of seeded rows (for JWT forge + BOLA test)
- Structlog `seed.done` w/ tenant counts

## Acceptance criteria
- [ ] Postgres seed completes < 3s; rows = 10 in `users`, 50 in `posts`, 10 in `settings`, 5 in `admins`, 2 in `universities`
- [ ] Firestore emulator seed completes < 5s; same row counts

## Test plan
```
Scenario: Postgres seed
  Steps: python -m sandbox.seed.postgres localhost:5432
  Expected: 10/50/10/5/2 row counts via select count(*)
Scenario: Firestore emulator seed
  Steps: python -m sandbox.seed.firestore localhost:8080 localhost:9099
  Expected: same counts via Auth REST + Firestore list
```

## Cross-references
- [see sandbox-isolation.md#db-mocks]
- [see system-design.md#jwt-forge-spec]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |