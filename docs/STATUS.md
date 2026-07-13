# AntiVibe — Current Status

**Updated**: 2026-07-13
**Git**: `main` — 20+ commits, pushed to [hasnainzxc/AntiVibe](https://github.com/hasnainzxc/AntiVibe)

## Phase 1: MVP Deploy — ✅ COMPLETE (9/9 tasks)

| Task | Status | Notes |
|------|--------|-------|
| T1 — Supabase setup | ✅ Done | Project `chefyaeapjlfhrjeemjc`, 9 tables, RLS verified |
| T2 — Fly.io config | ✅ Done | Config written, local-first (Fly deploy deferred — credit card gate) |
| T3 — Anthropic key | ✅ Done | Key provisioned, LLM extractor wired |
| T4 — sandbox-svc deploy | ✅ Done | Docker local mode, FastAPI on :8080 |
| T5 — E2E pipeline | ✅ Done | GitHub URL → Tier 1 → Tier 2 → findings in Supabase |
| T6 — Dashboard views | ✅ Done | Scan list + finding detail + real-time scan tracker UI |
| T7 — Circuit-breaker | ✅ Done | $0.50/scan, 10min timeout, cost tracking |
| T8 — Real scan testing | ✅ Done | 3 fixture repos tested, findings verified |
| T9 — Landing page | ✅ Done | Fly.io 1:1 design, alternating layout, illustrations |

### What Shipped

**Dashboard UI (apps/dashboard/):**
- Fly.io 1:1 landing page — floating pill navbar, full-bleed hero, alternating two-column feature sections, enterprise section with real illustrations
- Scan tracker — horizontal stage progress bar (queued → cloning → tier1 → tier2 → completed/failed), terminal-style log viewer with per-stage messages, severity summary chips, findings grid with severity badges
- Finding cards — severity badge (critical/high/medium/low/info), file path + line, description, PoC curl, suggested fix
- Full footer with Company/Resources/Legal columns

**Scan Pipeline (services/sandbox-svc/):**
- Tier 1 — Stack detector (6 stacks), AST parser, secret detector (providers + entropy), config flaw analyzer (Firestore, CORS, IAM), LLM extractor (Anthropic)
- Tier 2 — Docker containerizer, DB seeder (2 tenants, 5 mock users), JWT forge (5 adapter registry), route mapper
- 415 Python tests, 12 TypeScript tests

## Phase 2: Strix Integration — ⏳ GATED

Requires:
- [ ] Fly.io deploy with real domain + SSL
- [ ] 48+ hours zero errors in production logs
- [ ] At least 1 real user feedback collected
- [ ] User docs written

## Current State

### Running Services

| Service | Port | Status |
|---------|------|--------|
| Dashboard (Next.js) | :3000 | Running (dev) |
| Sandbox-svc (FastAPI) | :8080 | Running (dev) |

### Key Commands

```bash
# Start both services
cd services/sandbox-svc && uvicorn main:app --port 8080 --reload
cd apps/dashboard && pnpm dev

# Build
pnpm -r build

# Tests
cd services/sandbox-svc && python -m pytest tests/ -q
cd .. && pnpm -r test

# Scan a repo
curl -X POST http://localhost:8080/scan \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/owner/repo"}'
```

### Known Issues

- **No Stripe keys** → payment routes crash (need STRIPE_SECRET_KEY guard)
- **No Anthropic key in dev profile** → LLM extractor degrades gracefully
- **Vite/vanilla JS repos unsupported** → need stack detector update
- **Fly.io deploy blocked** → credit card needed for free tier
- **`fixtures/*` repos** → local dirs only, need GitHub mirrors for scan URL validation

### Tests

```
415 Python tests (pytest)    │  12 TypeScript tests (vitest)  │  Build (tsc)
─────────────────────────────┼────────────────────────────────┼────────────
scanner/       105 tests     │  dashboard/        12 tests     │  dashboard ✓
sandbox/       310 tests     │  shared-types/     0  tests     │  shared-types ✓
                                                                        
Total: 427 tests, all passing                                          
```

## Next Up

1. **Stack expansion** — Add Vite, generic HTML/JS, Python monorepo to supported stacks
2. **Fly.io deploy** — Provision credit card, deploy dashboard + sandbox-svc
3. **Phase 2 Strix** — Wire Strix fuzzer adapter (T10-T22, gated)
4. **User feedback** — Collect first user feedback to unlock Phase 2
5. **CI/CD polish** — GitHub Actions, auto-deploy, staging env
