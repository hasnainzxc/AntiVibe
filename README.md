# AntiVibe

<p align="center">
  <b>Agentic DevSecOps for VibeCoded Apps</b><br/>
  Paste a GitHub URL. Get an executive security report with working patches.
</p>

---

## What It Does

AntiVibe audits AI-generated codebases through a three-tier pipeline — static analysis, ephemeral sandboxing, and autonomous fuzz testing — producing actionable findings no static scanner catches alone.

Developers ship at vibe-coding speed. Firestore rules are left open, JWTs are unsigned, and multi-tenant data leaks past authorization checks. AntiVibe spins up the app in an isolated microVM, forges auth tokens for dummy tenants, and probes every endpoint the way a real attacker would — pivoting on 403s instead of giving up.

**Each scan produces**: a triaged vulnerability report (critical / high / medium / low) with Proof-of-Concept curl one-liners, affected code locations, and diff-ready remediation patches. An auto-generated PR ships the fixes alongside the report.

### Tiers

| Tier | What It Does | Runtime |
|------|-------------|---------|
| **1 — Static Engine** | AST parsing + regex secret detection + entropy analysis + LLM semantic review. Catches hardcoded keys, open Firestore rules, CORS wildcards, missing security headers. | < 5 min |
| **2 — Ephemeral Sandbox** | Spins up the app in a Fly Machine microVM with iptables egress DENY ALL. Seeds mock DBs, forges JWT tokens for cross-tenant users, builds a route index. | < 5 min |
| **3 — Fuzz Agent** | Walks every route, swaps tenant IDs, rotates HTTP methods, cycles forged tokens. No-stop pivot: 403 → adjacent path, POST → GET, token A → token B. | < 15 min |

---

## Project Structure

```
AntiVibe/
├── apps/dashboard/           # Next.js 16 App Router (shadcn/ui + Tailwind)
│   ├── src/middleware.ts     # Rate limiter (1 scan/hr/IP) + email gate
│   ├── lib/supabase/         # Browser + Server Supabase clients
│   ├── lib/storage/          # TS Storage client (private buckets)
│   └── tests/
├── packages/shared-types/    # Contract types + guards used by all tiers
│   └── src/index.ts          # Scan, Finding, Report, RouteShape, AuthStack
├── services/sandbox-svc/     # Python sandbox service — all scanner logic
│   ├── scanner/              # Tier 1: clone, detect, AST, secret, config, LLM
│   ├── sandbox/              # Tier 2-3: containerize, seed, spin, forge, fuzz
│   ├── fly/                  # Fly Machines async REST client
│   ├── storage/              # Supabase Storage (service-role, RLS bypass)
│   └── tests/                # 220 tests across scanner/ + sandbox/ + fly/
├── migrations/0001_init.sql  # Supabase schema (9 tables, RLS, CASCADE)
├── docs/                     # Architecture, system design, sprint goals, per-module specs
├── .github/workflows/        # CI (lint + test + build) + E2E (manual dispatch)
└── pnpm-workspace.yaml
```

### Stack (Locked for v1)

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Dashboard | Next.js 16 + Tailwind + shadcn/ui | App Router SSR, cookie-based auth refresh |
| Auth | Supabase Auth | Built-in RLS, session management, free tier |
| Database | Supabase Postgres | Row-level security, realtime subscriptions |
| Sandbox | Fly Machines (Firecracker µVMs) | Per-second billing, auto-destroy, sub-300ms boot |
| Scanner | Python 3.12 + asyncio | httpx, asyncpg, structlog, pytest |
| LLM | Anthropic Claude Sonnet (structural) + Together/Llama (fuzzing) | Dual-model avoids guardrail refusals |
| Monorepo | pnpm workspaces | Shared types, zero-hoist isolation |
| CI | GitHub Actions (Node 20 + Python 3.12) | Parallel lint/test/build |

---

## Quick Start

### Prerequisites

- Node.js ≥ 20
- pnpm (`corepack enable`)
- Python ≥ 3.12
- Git

### 1. Install

```bash
git clone https://github.com/<org>/AntiVibe
cd AntiVibe

# Node deps
pnpm install

# Python deps
cd services/sandbox-svc
pip install -r requirements.txt
cd ../..
```

### 2. Environment

```bash
cp apps/dashboard/.env.example apps/dashboard/.env.local
cp services/sandbox-svc/.env.example services/sandbox-svc/.env
# Edit .env files with your Supabase URL, anon key, service-role key
```

### 3. Run

```bash
# Dashboard (http://localhost:3000)
pnpm --filter apps/dashboard dev

# All tests
cd services/sandbox-svc && python -m pytest tests/ -v  # 220 tests
cd ../.. && pnpm -r test                                  # 19 TS tests

# Build check
pnpm -r build
```

### 4. Scan (Tier 1 in-memory example)

```python
from scanner.tier1 import run_tier1_sync

result = run_tier1_sync("https://github.com/owner/repo")
print(f"Status: {result['status']}")
print(f"Findings: {len(result['findings'])}")
# Output: list of findings from all analyzers (secret + config + LLM)
```

---

## Testing

```
220 Python tests (pytest)  │  19 TypeScript tests (vitest)  │  Build (tsc)
───────────────────────────┼────────────────────────────────┼────────────
scanner/       105 tests   │  dashboard/        12 tests    │  dashboard ✓
sandbox/       115 tests   │  shared-types/     7  tests   │  shared-types ✓
                                                                        
Total: 239 tests, all passing                                          
```

```bash
# Python
cd services/sandbox-svc && python -m pytest tests/ -v

# TypeScript
pnpm -r test -- --reporter=verbose

# Full CI pipeline
pnpm -r build && pnpm -r test && cd services/sandbox-svc && python -m pytest tests/ -v
```

---

## Infrastructure Setup

AntiVibe uses Supabase for Postgres, auth, and RLS. Before running the app, provision a Supabase project.

### Prerequisites

1. Create a free Supabase project at [supabase.com/dashboard](https://supabase.com/dashboard)
2. From **Settings → API**, copy:
   - **Project URL** → `NEXT_PUBLIC_SUPABASE_URL` / `SUPABASE_URL`
   - **anon public** key → `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - **service_role** key → `SUPABASE_SERVICE_ROLE_KEY`
3. Install the PostgreSQL client (`psql`) — required by the setup script

### Provision Schema

```bash
cp env.template apps/dashboard/.env.local
# Edit .env.local with real values from your Supabase project

SUPABASE_URL=https://<ref>.supabase.co \
SUPABASE_SERVICE_ROLE_KEY=eyJ... \
bash scripts/supabase-setup.sh
```

This script:
- Validates env vars are present
- Applies `migrations/0001_init.sql` (9 tables: users, scans, findings, reports, oauth_tokens, webhook_deliveries, subscriptions, scan_usage, sandbox_egress_log)
- Verifies all 9 tables exist after migration
- Exits with code 1 on any failure

### Verify RLS Policies

```bash
SUPABASE_URL=https://<ref>.supabase.co \
SUPABASE_ANON_KEY=eyJ... \
SUPABASE_SERVICE_ROLE_KEY=eyJ... \
bash scripts/verify-supabase-rls.sh
```

This script runs 3 curl-based tests against the Supabase REST API:
1. Unauthenticated read on `scans` — expects empty array
2. Service-role insert — expects 201 Created
3. Anon user trying to read another user's scan — expects empty array (RLS blocks it)

### Storage Buckets

After schema setup, create these private buckets in **Supabase Dashboard → Storage**:

| Bucket | Visibility | Purpose |
|--------|-----------|---------|
| `scan-artifacts` | Private | Per-scan output artifacts |
| `poc-captures` | Private | Encrypted PoC screenshots / captures |

---

## Docs

Full documentation lives in `docs/`:

| Doc | Covers |
|-----|--------|
| [architecture.md](docs/architecture.md) | System overview, component map, data flow |
| [system-design.md](docs/system-design.md) | Design decisions, tradeoffs, scaling strategy |
| [sprint-goals.md](docs/sprint-goals.md) | 20-week roadmap, sprint exit criteria |
| [STATUS.md](docs/STATUS.md) | Current build status, completed modules, next up |
| [features/](docs/features/) | Per-module specs (35 modules, 800-word cap each) |

---

## Guardrails

- **Cost**: $0.50/scan cap, 10min circuit-breaker
- **Sandbox egress**: DENY ALL except localhost, audit-logged
- **Clone safety**: shallow `--depth 1`, no LFS, 500MB cap, postinstall blocked
- **Auto-PR**: never auto-merged — human review mandatory
- **Secrets**: stripped from LLM input before API call
- **Rate limit**: 1 scan/hour/IP on free tier

---

## Progress

| Wave | Progress | Tests |
|------|----------|-------|
| 1 — Infra | 8/8 ✅ | — |
| 2 — Tier 1 Static Engine | 7/7 ✅ | — |
| 3 — Tier 2 Sandbox | 7/7 ✅ | — |
| 4 — Tier 3 Fuzz Agent | 0/7 | — |
| 5 — Reports + GitHub | 0/8 | — |
| 6 — Billing | 0/7 | — |
| 7 — Fixtures + Demo | 0/6 | — |
| FINAL — Review | 0/4 | — |

**22/50 implementation tasks complete (44%). 4 git commits. 239 total tests.**

---

## License

MIT
