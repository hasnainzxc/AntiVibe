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
| **3 — Fuzz Agent** | Phase 2: embeds [Strix](https://github.com/usestrix/strix) (Apache-2.0) for full OWASP Top 10 fuzzing — 23 vuln classes including BOLA/IDOR, SQLi, SSRF, SSTI, XSS, CSRF, mass assignment, race conditions. | < 15 min |

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
│   ├── sandbox/              # Tier 2: containerize, seed, spin, forge, fuzz
│   ├── fly/                  # Fly Machines async REST client
│   ├── storage/              # Supabase Storage (service-role, RLS bypass)
│   └── tests/                # 415 tests across scanner/ + sandbox/ + fly/
├── migrations/0001_init.sql  # Supabase schema (9 tables, RLS, CASCADE)
├── fixtures/                 # Test repos: vuln-nextjs, vuln-express, clean-app
├── scripts/                  # Setup scripts: supabase, verify-rls, generate-fixtures
├── .github/workflows/        # CI (parallel jobs) + staging deploy + prod deploy w/ rollback
├── docs/                     # Architecture, system design, sprint goals, per-module specs
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

## Services Architecture

AntiVibe runs **two services** locally:

| Service | Location | Port | Tech | Purpose |
|---------|----------|------|------|---------|
| **Dashboard** | `apps/dashboard/` | `:3000` | Next.js 16 | UI: landing page, scan form, progress tracker, findings display |
| **Sandbox-svc** | `services/sandbox-svc/` | `:8080` | Python 3.12 + FastAPI | Scan pipeline: clone, detect, analyze, sandbox, fuzz |

The dashboard proxies scan requests to sandbox-svc:
- `POST /api/scan` → `POST /scan` on sandbox-svc
- `GET /api/scan?scan_id=X` → `GET /scan/{id}/status` on sandbox-svc

---

## Quick Start (Local MVP)

Run the full AntiVibe pipeline locally — no Fly.io, no cloud deploy.

### Prerequisites

- Node.js ≥ 20 + pnpm (`corepack enable`)
- Python ≥ 3.12
- Docker (for sandbox containers in local mode)
- Supabase project (free tier) — [create one](https://supabase.com/dashboard)
  - Copy your Project URL, anon key, and service-role key from **Settings → API**
- Git

### 1. Install

```bash
git clone https://github.com/hasnainzxc/AntiVibe
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
# Dashboard
cp apps/dashboard/.env.example apps/dashboard/.env.local
# Edit with: NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY

# Sandbox service
cp services/sandbox-svc/.env.example services/sandbox-svc/.env
# Edit with: SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY
```

> **Note**: sandbox-svc auto-loads `.env` via `python-dotenv` on startup. Leave `FLY_API_TOKEN` unset — local mode uses Docker instead.

### 3. Start Services

**Terminal 1 — Sandbox-svc (Python backend):**
```bash
cd services/sandbox-svc
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
# Verifies: curl http://localhost:8080/health → {"status":"ok"}
```

**Terminal 2 — Dashboard (Next.js UI):**
```bash
cd apps/dashboard
pnpm dev
# Opens: http://localhost:3000
```

### 4. Scan a repo

Via the UI:
1. Open http://localhost:3000
2. Paste a GitHub URL: `https://github.com/hasnainzxc/vuln-nextjs`
3. Click "Scan your repo"
4. Watch the scan progress tracker with real-time terminal log

Via curl:
```bash
curl -X POST http://localhost:3000/api/scan \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/owner/repo"}'
```

### 5. Tests

```bash
# Python (415 tests)
cd services/sandbox-svc && python -m pytest tests/ -v

# TypeScript (12 tests)
cd ../.. && pnpm -r test

# Full CI pipeline
pnpm -r build && pnpm -r test && cd services/sandbox-svc && python -m pytest tests/ -v
```

---

## Supported Stacks

The scanner detects which framework a project uses and tailors its analyzers. Currently supports **6 stacks**:

| Stack | Detected By | Tier 2 Sandbox | Dockerfile |
|-------|-------------|---------------|------------|
| Next.js | `next.config.*`, `next/` in deps | ✅ Spins up, forges JWT, maps routes | `node:20-alpine` |
| Express | `express` in deps, `app.listen` | ✅ Spins up, forges JWT, maps routes | `node:20-alpine` |
| Firebase | `firebase.json` + `functions/` | ❌ (no sandbox) | — |
| FastAPI | `main.py` with `FastAPI()` | ❌ (Tier 1 only) | — |
| Flask | `app.py` with `Flask()` | ❌ (Tier 1 only) | — |
| SvelteKit | `svelte.config.*`, `@sveltejs` in deps | ❌ (Tier 1 only) | — |

Stacks without Tier 2 sandbox support still get full Tier 1 analysis (AST + secrets + config + LLM).

### Future Stacks (Planned)

| Stack | Priority | Notes |
|-------|----------|-------|
| **Vite / Vanilla JS** | High | Detected via `vite.config.*`; sandbox with `vite preview` |
| **Generic HTML/JS** | Medium | No framework, flat file analysis + template injection scan |
| **Python monorepo** | Medium | Multi-stack detection in monorepo layouts |
| **Nuxt.js** | Low | Vue-based Next.js alternative |
| **Remix** | Low | React Router-based framework |
| **Django** | Low | Python full-stack framework |
| **Spring Boot** | Low | Java/JVM-based (requires JDK sandbox) |

---

## Infrastructure Setup

### Supabase

AntiVibe uses Supabase for Postgres, auth, and RLS.

```bash
cp env.template apps/dashboard/.env.local
# Edit with real values from your Supabase project

SUPABASE_URL=https://<ref>.supabase.co \
SUPABASE_SERVICE_ROLE_KEY=eyJ... \
bash scripts/supabase-setup.sh
```

This script applies `migrations/0001_init.sql` (9 tables) and verifies all exist.

### Supabase Storage

Create these private buckets via **Supabase Dashboard → Storage**:

| Bucket | Visibility | Purpose |
|--------|-----------|---------|
| `scan-artifacts` | Private | Per-scan output artifacts |
| `poc-captures` | Private | Encrypted PoC screenshots / captures |

### Fly.io Deploy (Production)

```bash
flyctl launch --from-file apps/dashboard/fly.toml --no-deploy

flyctl secrets set \
  SUPABASE_URL="https://<ref>.supabase.co" \
  SUPABASE_ANON_KEY="<anon>" \
  SUPABASE_SERVICE_ROLE_KEY="<service-role>" \
  NODE_ENV="production"

flyctl deploy --config apps/dashboard/fly.toml
```

---

## Guardrails

- **Cost**: $0.50/scan cap, 10min circuit-breaker, 30min Strix wall-clock timeout
- **Sandbox egress**: DENY ALL except localhost, audit-logged
- **Strix worker egress**: ALLOW Anthropic API + target only
- **Clone safety**: shallow `--depth 1`, no LFS, 500MB cap, postinstall blocked
- **Auto-PR**: never auto-merged — human review mandatory
- **Secrets**: stripped from LLM input before API call; Strix PoCs encrypted at rest
- **Rate limit**: 1 scan/hour/IP on free tier
- **Strix**: v1 standard mode only; single Anthropic model; version pinned; Apache-2.0 NOTICE

---

## Progress

**Plan**: `.omo/plans/antivibe-mvp-and-strix.md` — 22 tasks, 2 phases

| Phase | Tasks | Status |
|-------|-------|--------|
| 1 — MVP Deploy | T1-T9 | **9/9 done** ✅ |
| 2 — Strix Integration | T10-T22 | GATED (requires Phase 1 polish + deploy) |
| Future — Stack Expansion | — | Planned: Vite, Vanilla JS, Nuxt, Django |
| FINAL — Review | F1-F4 | Pending |

**Complete**: T1 (Supabase), T2 (Fly.io), T3 (Anthropic key), T4 (sandbox-svc deploy prep), T5 (E2E pipeline), T6 (Dashboard views + scan tracker UI), T7 (Circuit-breaker), T8 (Real scan testing), T9 (Fly.io 1:1 landing page + scan UI)

**427 tests (415 Python + 12 TypeScript). Pushed to [hasnainzxc/AntiVibe](https://github.com/hasnainzxc/AntiVibe).**

---

## License

MIT
