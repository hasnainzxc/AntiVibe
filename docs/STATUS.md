# AntiVibe — Current Status

**Updated**: 2026-07-04
**Git**: 2 commits on main (c08b2df Waves 1-2, b784d88 Wave 3 pt1)

## Overall Progress

| Wave | Tasks | Status | Tests | Commit |
|------|-------|--------|-------|--------|
| 1 — Infra | 8/8 | ✅ complete | 124 (total) | c08b2df |
| 2 — Tier 1 Static Engine | 7/7 | ✅ complete | — | c08b2df |
| 3 — Tier 2 Sandbox | 5/7 | 🔄 in progress | 84 sandbox | b784d88 |
| 4 — Tier 3 Fuzz Agent | 0/7 | ⏳ not started | — | — |
| 5 — Reports + GitHub + Dashboard | 0/8 | ⏳ not started | — | — |
| 6 — Billing + Integration | 0/7 | ⏳ not started | — | — |
| 7 — Fixtures + YC Demo | 0/6 | ⏳ not started | — | — |
| FINAL — Review + QA | 0/4 | ⏳ not started | — | — |

**Total**: 22/50 implementation tasks done (44%), 0/4 review tasks

## Wave 3 Detail

| Task | Status | Tests |
|------|--------|-------|
| 16 App containerizer | ✅ | 14 |
| 17 Mock DB seeder | ✅ | 10 |
| 18 Sandbox spin-up | ✅ | 30 |
| 19 Route mapper | ✅ | 12 |
| 20 JWT forge | ✅ | 18 |
| 21 Health monitor | 🔄 in progress | — |
| 22 Tier 2 orchestrator | ⏳ pending | — |

## Completed Modules

### Wave 1 — Infrastructure
- Next.js 16 App Router dashboard (shadcn/ui, Tailwind)
- pnpm monorepo (apps/dashboard, packages/shared-types, services/sandbox-svc)
- Supabase schema (9 tables with RLS) + TS/Python clients
- Fly Machines async Python client (create/wait/destroy/list, auto-destroy)
- Supabase Storage client (TS + Python, private buckets)
- Rate limiter middleware (1 scan/hr/IP) + email verification gate
- GH Actions CI (Node 20 + Python 3.12, lint+test+build)
- Vitest workspace + Playwright + ESLint flat config + Ruff

### Wave 2 — Tier 1 Static Engine
- Secure repo cloner (shallow, LFS blocked, 500MB cap, postinstall blocked)
- Stack detector (6-stack heuristic whitelist)
- AST parser (per-stack route extraction + env-var scanning)
- Secret detector (provider patterns + Shannon entropy ≥3.5, FP controls)
- Config-flaw analyzer (Firestore rules AST, CORS wildcard, IAM broad-policy)
- LLM extractor (Anthropic client with 14-pattern secret sanitization)
- Tier 1 orchestrator (clone → detect → AST → parallel analyzers → merge, 60s circuit-breaker)

### Wave 3 — Tier 2 Sandbox (so far)
- 6-stack Dockerfile generator (never writes to user repo)
- Mock DB seeder (2 tenants × 5 users, cross-tenant BOLA schema)
- Sandbox spin-up (Fly Machine, iptables egress DENY ALL, auto-destroy)
- Route mapper (auth_required inference per 5 stacks)
- JWT forge (5 adapter registry: nextauth/clerk/firebase/supabase/custom)

## Next Up

Ordered by dependency:
1. Task 21 — Sandbox health monitor (boot detect + crash recovery)
2. Task 22 — Tier 2 orchestrator (chains containerize→seed→spin→forge)
3. Wave 4 — Tier 3 Fuzz Agent (route walker, BOLA tester, no-stop pivot engine)
4. Wave 5 — Reporting + GitHub + Dashboard (auto-PR writer, GitHub OAuth, webhook handler)
5. Wave 6 — Billing + Integration (Stripe, circuit-breaker, cost tracker, E2E)
6. Wave 7 — Fixtures + YC demo (vuln fixtures, benchmark runner, Playwright, demo recording)
7. FINAL — Review + QA (plan audit, code quality, manual QA, scope check)

## Need Revisiting

- [ ] Per-feature doc template compliance: some docs exceed 800-word cap
- [ ] Supabase project: NOT provisioned yet (migration exists, no deployed instance)
- [ ] Stripe integration: NOT configured (Stripe secret key not added to env)
- [ ] GitHub OAuth App: NOT registered
- [ ] Fly.io account: API token needed before real sandbox spin-up
- [ ] Anthropic API key: needed for LLM extractor real calls (mocked in tests)
- [ ] Together/Anyscale API key: needed for OSS inference in Wave 4
- [ ] Playwright E2E: config exists, no test scenarios written yet
