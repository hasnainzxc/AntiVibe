# AntiVibe Test Fixtures

3 local test repos for validating AntiVibe's scan pipeline.

## Fixture Repos

### `vuln-nextjs/` — Vulnerable Next.js App

| File | Vulnerability | Expected Finding |
|------|--------------|------------------|
| `pages/api/users/[id].ts` | IDOR — no auth check, returns any user by ID | Missing auth on user data endpoint |
| `pages/api/admin.ts` | Missing auth middleware — admin data exposed | Unauthenticated admin endpoint |
| `.env` | Hardcoded AWS secret key | Hardcoded secret in env file |

**Expected findings: 2-3**

### `vuln-express/` — Vulnerable Express App

| File | Vulnerability | Expected Finding |
|------|--------------|------------------|
| `index.js` | IDOR — `GET /api/orders/:id` no auth check | Missing auth on orders endpoint |
| `index.js` | No rate limiting on `POST /api/login` | Missing rate limit on auth endpoint |
| `index.js` | Hardcoded JWT secret | Hardcoded secret in source code |
| `routes/users.js` | No auth — returns all users | Unauthenticated user data exposure |
| `.env` | Hardcoded Stripe secret key | Hardcoded secret in env file |

**Expected findings: 3-4**

### `clean-app/` — Clean App (Control)

| File | Notes |
|------|-------|
| `pages/api/health.ts` | Public health check, no sensitive data |
| `pages/api/protected.ts` | Uses auth middleware — Bearer token required |
| `next.config.js` | Security headers enabled |
| `.env.example` | Placeholders only, no real secrets |

**Expected findings: 0**

## Usage

```bash
# Generate repos with git history
bash scripts/generate-fixtures.sh

# Run scanner against a fixture
python services/sandbox-svc/scanner/tier1.py fixtures/vuln-nextjs

# Verify git history
git -C fixtures/vuln-nextjs log --oneline
```

## Adding New Fixtures

1. Create a new directory under `fixtures/`
2. Add vulnerable files with deliberate patterns
3. Add entry to this README documenting expected findings
4. Update `generate-fixtures.sh` to include the new repo
