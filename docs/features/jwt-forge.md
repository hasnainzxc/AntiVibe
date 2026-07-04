# Feature: JWT Forge

**Purpose:** Mint authentic-looking JWTs for two seeded dummy users (User_A tenant1 student, User_B tenant2 admin) per supported auth-stack — enables cross-tenant BOLA testing.
**Wave:** 3  **Owner task:** 20  **Status:** pending

## Public API
```python
@dataclass
class ForgedToken:
    token: str
    user_id: str
    tenant_id: Literal[1, 2]
    role: UserRole
    auth_stack: AuthStack

class JWTForge:
    async def forge(self, *, auth_stack: AuthStack, env_root: Path, sandbox_seed: dict) -> tuple[ForgedToken, ForgedToken]:
        """Returns (User_A token, User_B token)."""
```

## Internal flow (per adapter)
- **NextAuth**: Read `NEXTAUTH_SECRET` env from `.env` in clone. Mint HS256 token w/ `{sub, email, role, tenant_id, iat, exp}` (1h exp). If secret missing → mint random HS256 w/ new secret.
- **Clerk**: Mock Clerk backend via fake JWKS server on sandbox localhost. Token includes `clerk_user_id` + `org_id` (tenant).
- **Firebase Auth**: Use Auth emulator's `createSessionCookie(uid, expires_in='3600')` for 2 pre-seeded users.
- **Supabase Auth**: `POST /auth/v1/token?grant_type=password` w/ admin client; receive access_token for each seeded user.
- **Custom**: Detect `JWT_SECRET` env or RSA pubkey in code. Detect algorithm from secret shape (HS256 vs RS256). Mint token w/ cloned-user claims.

All tokens include: `tenant_id`, `role`, `iat`, `exp` (1h sandbox scoped).

## Inputs
- auth_stack enum (Tier 1 detection)
- env_root: Path to cloned repo (to read env files)
- sandbox_seed: dict from MockDBSeeder (Task 17) w/ user identities

## Outputs
- tuple (User_A_forge, User_B_forge)
- Each ForgedToken has `.token` returned to orchestrator for cross-tenant swap

## Acceptance criteria
- [ ] All 5 adapters mint tokens valid against their respective verifiers on fixture repos
- [ ] User_A token reads tenant1 resources 200, tenant2 resources returns BOLA PoC if rules broken
- [ ] User_B token reads tenant2 resources 200
- [ ] Cross-tenant test (User_A token + tenant2 resource path) documented in PoC capture

## Test plan
```
Scenario: NextAuth forge + verify
  Steps: forge NextAuth HS256 token via NEXTAUTH_SECRET; validate via NextAuth server
  Expected: token decodes successfully w/ claims (sub, tenant_id=1, role=student)
Scenario: Custom JWT_SECRET forge w/ RS256
  Steps: forge w/ RSA pubkey; validate
  Expected: decodes successfully
```

## Cross-references
- [see system-design.md#jwt-forge-spec]
- [see sandbox-isolation.md#jwt-forge]
- [see security-threat-model.md#spoofing]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |