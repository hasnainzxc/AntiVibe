# AntiVibe — MVP Deploy + Strix Phase 2 (Gated)

## TL;DR

> **Quick Summary**: Phase 1 deploys Tier 1+2 pipeline to real infra, runs first real scans, polishes UX. Phase 2 (GATED — do not start until MVP is shipped and polished) embeds Strix (github.com/usestrix/strix, Apache-2.0) for full OWASP Top 10 API fuzzing coverage.
>
> **Deliverables (Phase 1)**:
> - Live Supabase project with schema + RLS
> - Fly.io deployed dashboard + sandbox-svc
> - Real Anthropic API key wired
> - End-to-end scan working on real repos (Next.js + Express)
> - Basic dashboard with scan results
>
> **Deliverables (Phase 2 - GATED)**:
> - Strix worker Fly Machine pool (Docker-enabled)
> - Subprocess adapter: `strix -n` → parse `vulnerabilities.json` → AntiVibe schema
> - Strix findings merged with Tier 1 static findings
> - Exec report + auto-PR + dashboard updated
> - 23 vuln classes covered via Strix (vs current BOLA-only)
>
> **Estimated Effort**: Phase 1 = 2 weeks; Phase 2 = 4-6 weeks (gated)
> **Parallel Execution**: YES — within each phase
> **GATE**: Phase 2 does NOT start until Phase 1 is deployed + real scan runs + user feedback collected

---

## Context

### Original Request
User wants AntiVibe SaaS — paste GitHub URL → security report with auto-PR. Three-tier pipeline: static scan (secret/config/LLM), sandbox spin-up (mock DB + JWT forge), fuzz agent (BOLA/IDOR). Current state: 15/50 tasks done (Waves 1-2), Waves 3 partial. 404 tests green. Zero infra deployed.

### Interview Summary
**Key Discussions**:
- **MVP First**: Deploy what's built (Tier 1+2). Get real scans running on real repos. Ship before adding Strix complexity.
- **Strix Deep Plan Ready**: Create detailed Strix integration plan NOW, but phase-gate it behind MVP polish. AGENTS.md enforces the gate.
- **Scope Cut for MVP**: Next.js + Express stacks only. NextAuth + custom JWT only. Postgres only (no Firestore). Docs kept as-is (well-written blueprints).
- **Pricing**: Single $29/mo tier with 20 scans/month. Free tier = 3 full scans (NOT Tier 1 only — let users feel the "wow" of sandbox).

**Research Findings** (Strix deep dive — librarian ses_0cc8adef8ffeCR6LFvOcR4K90A):
- Strix requires Docker daemon (Kali image 2-4GB). Needs SEPARATE Fly Machine worker — cannot run inside our sandbox microVM.
- Headless: `-n` flag. Exit codes: 0=clean, 1=error, 2=vulns found. Must handle exit code 2 explicitly.
- Output: always `./strix_runs/<run-name>/vulnerabilities.json`. Vuln schema: id, title, severity, cvss, cwe, cve, endpoint, method, poc_script_code, code_locations, agent_id.
- LLM: single model per scan via LiteLLM. `STRIX_LLM=anthropic/claude-sonnet-4-6`.
- Skills: 23 vuln classes dynamically loaded per agent. Strix does NOT let you selectively enable — it auto-picks per target fingerprint.
- Cost: `--max-budget-usd` for scan agents, but dedup calls per finding are EXTRA LLM cost (not covered by budget flag).
- License: Apache-2.0 (commercial OK, NOTICE required).

**Key Metis Concerns** (ses_0cc8adef8ffeCR6LFvOcR4K90A):
- No wall-clock timeout in Strix → we must wrap subprocess with `timeout=1800`
- Strix dedup LLM calls NOT in `--max-budget-usd` → actual cost higher than budget shows
- PoC scripts stored in `vulnerabilities.json` need encryption at rest (weaponized exploits)
- Docker container leak on process kill → need watchdog + prune
- `strix_runs/` disk accumulation → must purge after upload
- Worker egress allowlist: Anthropic API + target app only (Strix container probes external services)
- Separate Fly Machine needed for Strix worker (Docker-enabled, different from sandbox microVM)

### External Critique Review (Claude 4.8 assessment, verified)
- **Correct about**: 0% infra deployed, 404 tests (review understated at 239), scope is too broad, docs-to-code ratio high for pre-revenue
- **Wrong about**: test count (claimed 239, actual 404), git commits (claimed 4, actual 7)
- **Strategic advice adopted**: Ship MVP first → add Strix post- users. Cut Firestore, SvelteKit/Flask, extra JWT adapters for v1.

---

## Work Objectives

### Core Objective (Phase 1)
Deploy AntiVibe Tier 1+2 to production infra. Run end-to-end scans on real repos. Get first users.

### Core Objective (Phase 2 - GATED)
Embed Strix as subprocess dependency. Replace BOLA-only Tier 3 with full OWASP Top 10 API fuzzing via Strix adapter.

### Concrete Deliverables (Phase 1)
- Supabase project provisioned with schema + RLS
- Fly.io dashboard app deployed
- Fly.io sandbox-svc worker deployed
- Anthropic API key provisioned and wired
- End-to-end scan pipeline: GitHub URL → static findings → sandbox findings → report
- Dashboard: scan list + finding detail views
- 3 real repo scans completed successfully

### Concrete Deliverables (Phase 2 - GATED)
- `strix-agent` pip installed on dedicated Fly Machine worker pool
- Docker daemon running on Strix worker, image pre-pulled
- AntiVibe StrixAdapter module: subprocess wrapper, JSON parser, schema mapper
- Strix + Tier 1 finding merge + deduplication
- Updated report generator (Strix findings with `source: "strix"` flag)
- Auto-PR includes Strix-generated remediation code_locations
- NOTICE file (Apache-2.0) in repo
- Dashboard: findings tagged with source (`antivibe` vs `strix`)

### Definition of Done (Phase 1)
- [ ] Real scan of a Next.js repo runs end-to-end, produces findings, shows in dashboard
- [ ] Fly.io dashboard accessible at public URL
- [ ] Sandbox microVM spins up, app boots, health-check passes
- [ ] Anthropic LLM calls work with real API key
- [ ] $0.50/scan circuit breaker triggers correctly on test cases

### Definition of Done (Phase 2 - GATED)
- [ ] Strix adapter successfully completes scan on test repo, returns findings
- [ ] Strix exit code 2 handled as "success with findings" (not error)
- [ ] Strix findings merged with Tier 1 findings, deduplicated, sorted by CVSS
- [ ] Encrypted PoC scripts stored in Supabase
- [ ] `strix_runs/` purged after findings uploaded to Storage
- [ ] Docker container cleaned up after scan (success or failure)
- [ ] 30-min wall-clock timeout enforced on Strix subprocess

### Must Have (Phase 1)
- Working Supabase project with RLS
- Fly.io deploy (dashboard + worker)
- Anthropic API key wired
- End-to-end scan pipeline working
- Dashboard with scan results
- Circuit-breaker ($0.50/scan, 10min timeout)
- No hardcoded secrets in logs

### Must Have (Phase 2 - GATED)
- Strix adapter with proper exit code handling (0/1/2)
- `vulnerabilities.json` schema validated before parse
- Finding dedup across Strix + Tier 1
- PoC scripts encrypted at rest
- Worker egress allowlist (Anthropic API + target only)
- NOTICE file (Apache-2.0)
- `strix-agent` version pinned in requirements.txt
- Strix `--max-budget-usd 0.40` (leaves $0.10 for Tier 1 LLM)
- Wall-clock subprocess timeout 1800s

### Must NOT Have (All Phases)
- Auto-merge PRs (human review mandatory)
- Secrets in LLM input (sanitized before API call)
- Secrets in git history or logs
- Sandbox egress beyond allowlist
- Total scan cost exceeding $0.50
- Hardcoded API keys in config files
- Multi-model Strix scans (single Anthropic model only for v1)
- Strix deep scan mode (`standard` only for v1)
- Custom Strix skills (use built-in only)
- Firestore mock (Postgres only)
- SvelteKit/Flask/Firebase stack support (Next.js + Express only)
- Clerk/Firebase/Supabase JWT adapters (NextAuth + custom HS256 only)

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES (pytest 392 tests, vitest 12 tests)
- **Automated tests**: Tests-after for new code; existing tests stay
- **Framework**: pytest + vitest
- **Agent-Executed QA**: ALWAYS mandatory for all tasks

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`.

- **API/Backend**: Use Bash (curl) — Send requests, assert status + response fields
- **TUI/CLI**: Use interactive_bash (tmux) — Run command, validate output
- **Frontend/UI**: Use Playwright — Navigate, interact, assert DOM, screenshot

---

## Execution Strategy

### PHASE GATE (CRITICAL — Read Before Any Task Execution)

> **Phase 2 tasks (T10-T22) are STRICTLY GATED behind Phase 1 completion.**
>
> The executing agent (Sisyphus) MUST verify ALL these conditions before starting ANY Phase 2 task:
> 1. Phase 1 tasks T1-T9 all marked complete
> 2. At least 3 real repos scanned end-to-end successfully
> 3. Dashboard publicly accessible with scan results visible
> 4. 0 unhandled errors in production logs for 48+ hours
> 5. At least 1 real user feedback collected (even if just a friend)
>
> **If ANY condition fails: STOP. Do not start Phase 2. Return to Phase 1 fixes.**

### Phase 1: MVP Deploy (2 weeks, 9 tasks)

```
Wave 1 (Infra Provisioning — 4 tasks parallel):
├── T1: Provision Supabase project + run migrations + verify RLS
├── T2: Provision Fly.io org + deploy dashboard app
├── T3: Provision Anthropic API key + wire to sandbox-svc
├── T4: Deploy sandbox-svc worker to Fly.io

Wave 2 (Pipeline Integration — 3 tasks parallel):
├── T5: Wire end-to-end scan pipeline (GitHub URL → Tier 1 → Tier 2 → report)
├── T6: Dashboard: scan list + finding detail views
├── T7: Circuit-breaker validation + cost tracking

Wave 3 (Polish + Ship — 2 tasks):
├── T8: Real scan testing (3 repos, verify findings)
├── T9: Landing page + Stripe checkout ($29/mo tier)
```

### Phase 2: Strix Integration (GATED — 4-6 weeks, 13 tasks)

```
Wave 4 (Strix Worker Infra — 3 tasks parallel):
├── T10: Provision Strix worker Fly Machine (Docker-enabled, 2GB+ RAM)
├── T11: Install strix-agent + pre-pull Docker image
├── T12: Worker egress allowlist + network rules

Wave 5 (Strix Adapter — 4 tasks parallel):
├── T13: StrixAdapter: subprocess wrapper + exit code handling
├── T14: Strix findings parser (vulnerabilities.json → AntiVibe schema)
├── T15: PoC script encryption + secure storage
├── T16: Finding merge + dedup (Strix + Tier 1)

Wave 6 (Integration — 4 tasks parallel):
├── T17: Updated report generator (Strix findings w/ source tag)
├── T18: Updated auto-PR writer (Strix code_locations)
├── T19: Dashboard: findings source badges (antivibe vs strix)
├── T20: End-to-end Strix scan integration svc

Wave 7 (Polish — 2 tasks):
├── T21: Strix worker cleanup (purge, watchdog, prune)
├── T22: Benchmark + FP validation on fixture repos
```

### Phase Gate Enforcement in AGENTS.md

```markdown
## PHASE 2 GATE (CRITICAL)

Phase 2 (Strix Integration, tasks T10-T22 in .omo/plans/antivibe-mvp-and-strix.md)
MUST NOT be started until ALL of:
1. Phase 1 tasks T1-T9 marked complete in plan file
2. 3+ real repos scanned end-to-end successfully
3. Dashboard publicly accessible with scan results
4. 0 unhandled errors in production logs for 48+ hours
5. 1+ real user feedback collected

If any condition fails: STOP. Fix Phase 1. Do not touch Phase 2.
```

This will be inserted into `/home/hairzee/prods/AntiVibe/AGENTS.md`.

---

## TODOs

> **FORMAT**: Task labels use bare numbers: `1.`, `2.`, `3.` — NOT `T1.`, `Task 1.`.
> Every task MUST have: Recommended Agent Profile + QA Scenarios (happy path + failure).
> Phase 2 tasks (T10-T22) are GATED — see Phase Gate above.

- [x] 1. Provision Supabase project + run migrations + verify RLS

  **What to do**:
  - Create Supabase project (free tier OK for MVP)
  - Run `migrations/0001_init.sql` against the project
  - Verify all 9 tables created with correct RLS policies
  - Set up service-role key + anon key as env vars on Fly.io
  - Create `.env.local` with real Supabase URL + keys for dashboard

  **Must NOT do**:
  - Do not hardcode keys in source files
  - Do not expose service-role key to client-side code
  - Do not skip RLS verification

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: none needed (Supabase dashboard operations)

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T2, T3)
  - **Blocks**: T5, T6
  - **Blocked By**: None

  **References**:
  - `migrations/0001_init.sql` — Full schema (9 tables, RLS, CASCADE). Run this as-is.
  - `apps/dashboard/.env.example` — Env var template to fill with real values
  - `services/sandbox-svc/.env.example` — Env var template for sandbox-svc

  **Acceptance Criteria**:
  - [ ] Supabase project URL returns 200 on health check
  - [ ] `psql` or Supabase SQL editor confirms all 9 tables exist
  - [ ] RLS test: unauthenticated query against `scans` table returns 0 rows (not error)
  - [ ] Service-role key can insert into `scans` table

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Verify Supabase connection + RLS policies
    Tool: Bash (curl)
    Preconditions: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY set in env
    Steps:
      1. curl -H "apikey: $SUPABASE_ANON_KEY" "$SUPABASE_URL/rest/v1/scans?select=count"
      2. Assert HTTP 200, response is empty array []
      3. curl -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" -H "apikey: $SUPABASE_ANON_KEY" "$SUPABASE_URL/rest/v1/scans" -d '{"repo_url":"test"}' -H "Content-Type: application/json"
      4. Assert HTTP 201 (created)
      5. Repeat step 1 — now returns 1 row
    Expected Result: RLS blocks unauthenticated reads; service-role can insert. Row count increments.
    Evidence: .omo/evidence/task-1-supabase-rls.txt

  Scenario: Failed connection handling
    Tool: Bash (curl)
    Preconditions: Invalid SUPABASE_URL set
    Steps:
      1. curl "$INVALID_SUPABASE_URL/rest/v1/scans" -H "apikey: fake"
      2. Assert connection refused or timeout (not 200)
    Expected Result: Clear error message, no data leaked
    Evidence: .omo/evidence/task-1-supabase-error.txt
  ```

  **Commit**: NO (infra provisioning, not code)

---

- [~] 2. Provision Fly.io org + deploy dashboard app
  *DEFERRED* — using local dev mode instead. Dashboard runs on :3000 via `pnpm dev`.
  Revisit when ready for production deployment.

  **What to do**:
  - Create Fly.io account (free tier)
  - Install `flyctl` CLI + authenticate
  - Create `fly.toml` for dashboard app (Next.js, port 3000)
  - Deploy dashboard via `fly deploy`
  - Verify dashboard accessible at `<app>.fly.dev`
  - Set Supabase env vars as Fly secrets

  **Must NOT do**:
  - Do not commit real API keys to repo
  - Do not expose sandbox-svc port publicly (internal-only)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: none needed

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1, T3)
  - **Blocks**: T4 (need Fly org for sandbox-svc), T6 (dashboard URL needed)
  - **Blocked By**: None

  **References**:
  - `apps/dashboard/package.json` — build commands, dependencies
  - `apps/dashboard/next.config.ts` — Next.js config for production

  **Acceptance Criteria**:
  - [ ] `curl https://<app>.fly.dev` returns HTTP 200
  - [ ] Dashboard renders (Next.js SSR working)
  - [ ] Fly secrets contain all required env vars

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Dashboard is publicly accessible
    Tool: Playwright
    Preconditions: Deployed dashboard URL known
    Steps:
      1. Navigate to https://<app>.fly.dev
      2. Wait for page load (timeout: 15s)
      3. Assert page title contains "AntiVibe"
      4. Take screenshot of landing page
    Expected Result: Dashboard renders with AntiVibe branding
    Evidence: .omo/evidence/task-2-dashboard-landing.png

  Scenario: Dashboard handles 404 gracefully
    Tool: Bash (curl)
    Preconditions: Dashboard running
    Steps:
      1. curl -s -o /dev/null -w "%{http_code}" https://<app>.fly.dev/nonexistent
      2. Assert HTTP 404 (not 500, not blank page)
    Expected Result: 404 page rendered, no crash
    Evidence: .omo/evidence/task-2-dashboard-404.txt
  ```

  **Commit**: NO (infra)

---

- [x] 3. Provision Anthropic API key + wire to sandbox-svc

  **What to do**:
  - Create Anthropic API key at console.anthropic.com
  - Set `ANTHROPIC_API_KEY` as Fly secret on sandbox-svc
  - Verify LLM extractor works with real key (test call)
  - Log token usage for cost tracking

  **Must NOT do**:
  - Do not log the raw API key anywhere
  - Do not commit key to repo
  - Do not exceed $0.10 budget on test calls

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: none needed

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1, T2)
  - **Blocks**: T5 (scan pipeline needs LLM)
  - **Blocked By**: None

  **References**:
  - `services/sandbox-svc/scanner/llm_extractor.py` — LLM client code, verify API key env var name
  - `services/sandbox-svc/.env.example` — ANTHROPIC_API_KEY placeholder

  **Acceptance Criteria**:
  - [ ] Test LLM call succeeds (`curl` to Anthropic API with key returns 200)
  - [ ] LLM extractor module loads and initializes without error
  - [ ] Token usage logged to structlog

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Anthropic API key works with LLM extractor
    Tool: interactive_bash (tmux)
    Preconditions: ANTHROPIC_API_KEY set, sandbox-svc installed
    Steps:
      1. cd services/sandbox-svc && python -c "
         from scanner.llm_extractor import LLMExtractor
         import os
         assert os.environ['ANTHROPIC_API_KEY'].startswith('sk-ant-')
         print('API key detected')
         "
      2. Assert output contains "API key detected"
    Expected Result: Key visible, module imports without error
    Evidence: .omo/evidence/task-3-llm-key-check.txt

  Scenario: Invalid key produces clear error
    Tool: interactive_bash (tmux)
    Preconditions: Set ANTHROPIC_API_KEY to "sk-ant-invalid"
    Steps:
      1. Attempt LLM call with invalid key
      2. Assert error message mentions "authentication" or "401" (not crash)
    Expected Result: Graceful error, not stack trace
    Evidence: .omo/evidence/task-3-llm-error.txt
  ```

  **Commit**: NO (infra)

---

- [~] 4. Deploy sandbox-svc worker to Fly.io
  *DEFERRED* — using local Docker mode instead. Sandbox-svc runs on :8080 via `uvicorn`.
  Revisit when ready for production deployment.

  **What to do**:
  - Create `fly.toml` for sandbox-svc (Python, internal-only)
  - Set Fly secrets: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, ANTHROPIC_API_KEY, FLY_API_TOKEN
  - Deploy via `fly deploy`
  - Verify worker health endpoint returns 200
  - Configure Fly internal networking (dashboard ↔ sandbox-svc via `.internal`)

  **Must NOT do**:
  - Do not expose sandbox-svc on public internet (internal-only)
  - Do not deploy sandbox-svc without egress rules

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: none needed

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T3 if T2 done)
  - **Parallel Group**: Wave 1 tail
  - **Blocks**: T5 (scan pipeline needs worker)
  - **Blocked By**: T2 (need Fly org)

  **References**:
  - `services/sandbox-svc/pyproject.toml` or `requirements.txt` — Python deps
  - `services/sandbox-svc/scanner/tier1.py` — Entry point, verify it works
  - `services/sandbox-svc/fly/client.py:305` — Fly Machines client, verify FLY_API_TOKEN access

  **Acceptance Criteria**:
  - [ ] `fly status` shows sandbox-svc running
  - [ ] Health endpoint returns 200 internally
  - [ ] Fly secrets all set (verified via `fly secrets list`)

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Worker health check
    Tool: Bash (curl)
    Preconditions: Worker deployed, internal DNS resolves
    Steps:
      1. curl -s -o /dev/null -w "%{http_code}" http://sandbox-svc.internal:8080/health
      2. Assert HTTP 200
    Expected Result: Worker responds healthy
    Evidence: .omo/evidence/task-4-worker-health.txt

  Scenario: Worker not accessible publicly
    Tool: Bash (curl)
    Preconditions: Worker deployed
    Steps:
      1. curl -s -o /dev/null -w "%{http_code}" https://sandbox-svc.fly.dev --connect-timeout 5
      2. Assert timeout or connection refused (not 200)
    Expected Result: Public access denied
    Evidence: .omo/evidence/task-4-worker-isolated.txt
  ```

  **Commit**: NO (infra)

---

- [x] 5. Wire end-to-end scan pipeline (GitHub URL → Tier 1 → Tier 2 → report)

  **What to do**:
  - Create scan orchestrator endpoint: accepts GitHub URL → triggers clone → runs Tier 1 → runs Tier 2 → aggregates findings → saves to Supabase
  - Wire Tier 1 static engine (already built — scanner/tier1.py)
  - Wire Tier 2 sandbox (containerizer → seed → spin → health → routes → JWT forge)
  - Handle errors gracefully: if Tier 2 fails, return Tier 1 results
  - Log every stage with structured logging
  - Circuit-breaker: stop at $0.50 or 10min

  **Must NOT do**:
  - Do not rewrite Tier 1 or Tier 2 code (they work — wire them)
  - Do not skip error handling (Tier 2 failure must not crash pipeline)
  - Do not expose internal errors to user (sanitize error messages)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: none
  - **Reason**: Orchestration across multiple modules, error handling complexity

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on T1-T4 infra)
  - **Parallel Group**: Wave 2 (sequential — integration task)
  - **Blocks**: T6, T8
  - **Blocked By**: T1, T2, T3, T4

  **References**:
  - `services/sandbox-svc/scanner/tier1.py` — Tier 1 orchestrator (already built, T15 in old plan)
  - `services/sandbox-svc/sandbox/tier2_orchestrator.py` — Tier 2 orchestrator (T22 in old plan)
  - `services/sandbox-svc/scanner/repo_cloner.py` — Clone module with safety guards

  **Acceptance Criteria**:
  - [ ] Scan endpoint accepts GitHub URL, returns scan ID
  - [ ] Tier 1 completes in <5min, Tier 2 in <10min
  - [ ] Findings saved to Supabase with scan_id FK
  - [ ] Circuit-breaker triggers on token/cost limits
  - [ ] Failed Tier 2 returns Tier 1 results (graceful degradation)

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: End-to-end scan on public repo
    Tool: Bash (curl)
    Preconditions: All services running, keys set
    Steps:
      1. curl -X POST http://sandbox-svc.internal:8080/scan \
         -H "Content-Type: application/json" \
         -d '{"repo_url":"https://github.com/hasnainzxc/test-nextjs-app"}'
      2. Assert HTTP 202 (accepted), response contains scan_id
      3. Poll GET /scan/{scan_id}/status until status=completed (max 15min)
      4. GET /scan/{scan_id}/findings — assert findings array non-empty
      5. Assert at least one finding has severity "high" or "critical"
    Expected Result: Scan completes, findings returned with severities
    Evidence: .omo/evidence/task-5-e2e-scan.json

  Scenario: Invalid repo URL returns error
    Tool: Bash (curl)
    Preconditions: Services running
    Steps:
      1. curl -X POST http://sandbox-svc.internal:8080/scan \
         -H "Content-Type: application/json" \
         -d '{"repo_url":"not-a-valid-url"}'
      2. Assert HTTP 400, error message mentions "invalid URL"
    Expected Result: Clear validation error, no crash
    Evidence: .omo/evidence/task-5-invalid-url.txt

  Scenario: Circuit-breaker triggers on runaway scan
    Tool: Bash (curl)
    Preconditions: Circuit-breaker configured at 10s for testing
    Steps:
      1. Submit scan of large repo known to exceed circuit
      2. Wait for scan status to become "stopped" (not "completed")
      3. Assert findings contain partial results (not empty)
    Expected Result: Scan stopped cleanly, partial findings returned
    Evidence: .omo/evidence/task-5-circuit-breaker.txt
  ```

  **Commit**: YES (groups with T6)
  - Message: `feat(pipeline): wire end-to-end scan orchestrator — GitHub URL → Tier 1 → Tier 2 → Supabase`
  - Files: `services/sandbox-svc/scanner/scan_orchestrator.py`, related changed files

---

- [x] 6. Dashboard: scan list + finding detail views

  **What to do**:
  - Build scan list page: shows all user's scans with status, repo name, finding count, timestamp
  - Build finding detail page: severity badge, description, code location, remediation, PoC curl
  - Wire to Supabase for real data
  - Loading states, empty states, error states for all views
  - Responsive: works on desktop + mobile

  **Must NOT do**:
  - Do not show other users' scans (RLS enforced)
  - Do not expose raw PoC scripts without "click to reveal" pattern
  - Do not hardcode scan data (fetch from Supabase)

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
  - **Skills**: none
  - **Reason**: Frontend UI with loading/empty/error states, responsive design

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with T7)
  - **Blocks**: T8 (scan testing shows dashboard), T9 (landing page)
  - **Blocked By**: T1 (Supabase), T5 (pipeline — need scan data to display)

  **References**:
  - `apps/dashboard/src/` — Existing dashboard skeleton
  - `packages/shared-types/src/index.ts` — Scan, Finding types
  - `apps/dashboard/lib/supabase/` — Supabase client patterns

  **Acceptance Criteria**:
  - [ ] Scan list shows all user's scans with correct status badges
  - [ ] Empty state shown when no scans exist
  - [ ] Finding detail shows severity, description, code location, remediation
  - [ ] PoC curl hidden behind toggle (security UX)
  - [ ] Mobile responsive (viewport test at 375px)

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Scan list shows completed scan
    Tool: Playwright
    Preconditions: At least 1 completed scan in Supabase
    Steps:
      1. Navigate to dashboard (authenticated)
      2. Wait for scan list to load
      3. Assert at least 1 scan card visible with repo name, status "completed", finding count
      4. Take screenshot
    Expected Result: Scan card renders with correct data
    Evidence: .omo/evidence/task-6-scan-list.png

  Scenario: Finding detail page shows full info
    Tool: Playwright
    Preconditions: Completed scan with findings in Supabase
    Steps:
      1. Click on a scan card to open detail
      2. Assert severity badge visible (critical = red, high = orange)
      3. Assert code location with filename + line numbers
      4. Click "Show PoC" toggle
      5. Assert curl command visible
      6. Take screenshot of finding detail
    Expected Result: Full finding detail rendered correctly
    Evidence: .omo/evidence/task-6-finding-detail.png

  Scenario: Empty state when no scans
    Tool: Playwright
    Preconditions: Fresh account, 0 scans
    Steps:
      1. Navigate to dashboard (authenticated, new user)
      2. Assert empty state message visible ("No scans yet" or similar)
      3. Assert CTA button ("Start your first scan") present
    Expected Result: Empty state guides user to action
    Evidence: .omo/evidence/task-6-empty-state.png
  ```

  **Commit**: YES (groups with T5)
  - Message: `feat(dashboard): add scan list + finding detail views with Supabase integration`
  - Files: `apps/dashboard/src/`

---

- [x] 7. Circuit-breaker validation + cost tracking

  **What to do**:
  - Test circuit-breaker triggers correctly: $0.50 cap, 10min timeout, 100K token limit
  - Test partial results returned when breaker triggers (not empty)
  - Add cost tracking: LLM token count × Anthropic pricing + Fly Machine seconds × per-second rate
  - Log cost per scan to structlog + Supabase
  - Verify breaker resets between scans (no state leak)

  **Must NOT do**:
  - Do not let a triggered breaker crash the worker
  - Do not lose scan data when breaker triggers (save partial findings)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: none
  - **Reason**: Edge case testing, cost math verification, state management

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with T6)
  - **Blocks**: T8 (validated pipeline)
  - **Blocked By**: T5 (pipeline)

  **References**:
  - `services/sandbox-svc/scanner/tier1.py` — Existing circuit-breaker implementation
  - `services/sandbox-svc/scanner/llm_extractor.py` — Token counting logic

  **Acceptance Criteria**:
  - [ ] Circuit-breaker triggers at $0.50 exactly (test with mock pricing)
  - [ ] Partial findings saved when breaker triggers
  - [ ] Cost logged per scan in Supabase (`scans.cost_cents` field)
  - [ ] Breaker state does not leak between scans

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Cost cap triggers circuit breaker
    Tool: interactive_bash (tmux)
    Preconditions: Circuit set to $0.01 (test mode)
    Steps:
      1. Submit scan of repo known to trigger LLM calls above 1 cent
      2. Wait for scan status "stopped"
      3. Check scan record in Supabase: cost_cents >= 1, status = "stopped"
      4. Assert findings array non-empty (partial results saved)
    Expected Result: Breaker triggers cleanly, partial data preserved
    Evidence: .omo/evidence/task-7-breaker-trigger.txt

  Scenario: Breaker resets between scans
    Tool: interactive_bash (tmux)
    Preconditions: Previous scan stopped by breaker
    Steps:
      1. Submit new scan of small repo
      2. Assert scan completes normally (status "completed", not "stopped")
      3. Assert cost_cents < 1 (below test breaker cap)
    Expected Result: New scan unaffected by previous breaker state
    Evidence: .omo/evidence/task-7-breaker-reset.txt
  ```

  **Commit**: YES
  - Message: `test(pipeline): validate circuit-breaker behavior + cost tracking accuracy`
  - Files: `services/sandbox-svc/tests/`

---

- [x] 8. Real scan testing (3 repos, verify findings)
  *UNBLOCKED* — local Docker mode enables Tier 2 sandbox without Fly.
  Run scans against fixture repos via `curl -X POST http://localhost:8080/scan`.

  **What to do**:
  - Scan 3 real public repos that are known to have security issues:
    1. Next.js app with open API routes + hardcoded secrets
    2. Express app with missing auth middleware
    3. Clean app (known-clean) to verify FP rate
  - Document findings per repo: what was found, severity, FP count
  - Tune detection thresholds if FP rate >10%
  - Verify sandbox spin-up works on all 3 (container build, health check, route mapping)

  **Must NOT do**:
  - Do not scan repos you don't have permission to test
  - Do not publish findings publicly (security issues in other people's repos)
  - Do not skip the clean-repo test (FP rate validation is critical)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: none
  - **Reason**: Manual testing + tuning, requires judgment

  **Parallelization**:
  - **Can Run In Parallel**: NO (sequential scan testing)
  - **Parallel Group**: Wave 3 (sequential)
  - **Blocks**: T9 (landing page mentions results)
  - **Blocked By**: T5, T6, T7

  **References**:
  - Known test repos (create if needed — fixture repos from old plan Wave 7)
  - `services/sandbox-svc/scanner/secret_detector.py` — FP controls
  - `services/sandbox-svc/scanner/config_flaws.py` — Config flaw detection

  **Acceptance Criteria**:
  - [ ] 3 scans complete successfully (status = "completed")
  - [ ] At least 2 findings on vulnerable repos (1+ critical/high each)
  - [ ] Clean repo: 0 findings (or all low-severity with explanation)
  - [ ] FP rate <10% across all scans
  - [ ] Scan latency: Tier 1 <5min, Tier 2 <10min p95

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Vulnerable Next.js app produces security findings
    Tool: Bash (curl) + Playwright (dashboard)
    Preconditions: Pipeline running, test repo URL known
    Steps:
      1. Submit scan of vulnerable Next.js test repo
      2. Wait for completion (max 15min)
      3. Assert findings contain at least 1 "critical" or "high" severity
      4. Open dashboard, assert findings visible with correct severity badges
    Expected Result: Real vulnerabilities detected and displayed
    Evidence: .omo/evidence/task-8-scan-vuln-nextjs.json

  Scenario: Clean repo produces no false positives
    Tool: Bash (curl)
    Preconditions: Clean test repo URL known (no secrets, correct configs)
    Steps:
      1. Submit scan of clean test repo
      2. Wait for completion
      3. Assert findings array length = 0 (or all low-severity with clear explanation)
    Expected Result: Zero false positives on clean code
    Evidence: .omo/evidence/task-8-scan-clean.json

  Scenario: Scan latency within budget
    Tool: Bash (curl)
    Preconditions: Pipeline running
    Steps:
      1. Submit 3 scans, record start + completion timestamps
      2. Assert Tier 1 duration <300s for all 3
      3. Assert Tier 2 duration <600s for all 3
    Expected Result: All scans within p95 latency budget
    Evidence: .omo/evidence/task-8-latency.txt
  ```

  **Commit**: NO (testing activity)

---

- [x] 9. Landing page + Stripe checkout ($29/mo)

  **What to do**:
  - Build landing page: hero ("Paste a GitHub URL. Get a security report."), how it works (3 tiers visual), pricing card
  - Stripe integration: create product + price in Stripe dashboard, embed checkout session
  - Single tier: $29/mo, 20 scans/month, full 3-tier coverage
  - Free tier: 3 full scans (gate via email verification, not credit card)
  - Post-checkout: webhook creates/upgrades user in Supabase
  - Error states: payment failed, session expired, already subscribed

  **Must NOT do**:
  - Do not gate free tier behind credit card (email gate only)
  - Do not store raw credit card numbers
  - Do not skip webhook signature verification

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
  - **Skills**: none
  - **Reason**: Marketing page + payment integration with UI polish

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (after T8)
  - **Blocks**: None
  - **Blocked By**: T6 (dashboard UX informs landing page design)

  **References**:
  - `apps/dashboard/src/` — Existing app structure for routing
  - Stripe Checkout docs: https://stripe.com/docs/payments/checkout
  - Stripe Webhooks docs: https://stripe.com/docs/webhooks

  **Acceptance Criteria**:
  - [ ] Landing page renders at `/` with clear value prop
  - [ ] "Start Free" button initiates email verification flow
  - [ ] "$29/mo" button opens Stripe Checkout
  - [ ] Successful payment upgrades user tier in Supabase
  - [ ] Webhook signature verified (HMAC)
  - [ ] Failed payment shows error, doesn't crash

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Landing page loads and shows pricing
    Tool: Playwright
    Preconditions: Dashboard deployed
    Steps:
      1. Navigate to https://<app>.fly.dev
      2. Assert hero text visible: "Paste a GitHub URL" or similar
      3. Assert $29/mo pricing card visible
      4. Assert "Start Free" CTA visible
      5. Take screenshot
    Expected Result: Polished landing page with clear conversion path
    Evidence: .omo/evidence/task-9-landing-page.png

  Scenario: Stripe Checkout opens correctly
    Tool: Playwright
    Preconditions: Stripe keys configured
    Steps:
      1. Click "$29/mo" button on landing page
      2. Assert redirected to Stripe Checkout (URL contains "checkout.stripe.com")
      3. Cancel the checkout (don't pay real money)
      4. Assert redirected back to landing page with "Payment cancelled" message
    Expected Result: Checkout flow works, cancellation handled gracefully
    Evidence: .omo/evidence/task-9-stripe-checkout.png

  Scenario: Free tier email gate works
    Tool: Playwright
    Preconditions: Email gate configured
    Steps:
      1. Click "Start Free" on landing page
      2. Enter test@antivibe.example in email field
      3. Assert verification email sent message (or redirect to dashboard if no email gate)
    Expected Result: Email gate functional, user can access free tier
    Evidence: .omo/evidence/task-9-free-tier.png
  ```

  **Commit**: YES
  - Message: `feat(web): add landing page + Stripe $29/mo checkout + free tier email gate`
  - Files: `apps/dashboard/src/`

---

---
## PHASE 2 — Strix Integration (GATED — DO NOT START until Phase 1 complete)
---

- [~] 10. Provision Strix worker Fly Machine (Docker-enabled, 2GB+ RAM)

  **What to do**:
  - Create new Fly Machine type: `strix-worker` (separate from sandbox-svc)
  - Size: shared-cpu-2x (for Docker daemon), 2GB RAM, 10GB volume
  - Enable Docker via Fly's Docker-enabled Machine template or install Docker in entrypoint script
  - Configure internal networking (worker can reach sandbox-svc.internal)
  - Set Fly secrets: ANTHROPIC_API_KEY, LLM_API_KEY (for Strix), PERPLEXITY_API_KEY (optional)
  - Health check: Docker daemon running + `strix --version` returns successfully
  - Mount persistent volume for Docker image cache (`/var/lib/docker`)

  **Must NOT do**:
  - Do not re-use sandbox-svc for Strix (separate worker, separate Docker daemon)
  - Do not expose Strix worker publicly

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: none

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with T11, T12)
  - **Blocks**: T13 (adapter needs worker)
  - **Blocked By**: None (infra-only, independent of Phase 1)

  **References**:
  - Fly.io Docker docs: fly.io/docs/apps/dockerfile/
  - `services/sandbox-svc/fly/` — Fly client patterns to follow

  **Acceptance Criteria**:
  - [ ] `fly status` shows `strix-worker` running
  - [ ] `docker ps` inside worker succeeds
  - [ ] `strix --version` returns version string
  - [ ] Worker health endpoint returns 200

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Worker has Docker + Strix installed
    Tool: Bash (ssh into Fly Machine)
    Preconditions: Worker provisioned
    Steps:
      1. fly ssh console -a antivibe-strix-worker
      2. docker --version → assert Docker version string
      3. strix --version → assert Strix version string
      4. docker ps → assert no existing containers running
    Expected Result: Docker daemon running, Strix installed
    Evidence: .omo/evidence/task-10-worker-ready.txt
  ```

  **Commit**: NO (infra)

---

- [~] 11. Install strix-agent + pre-pull Docker image

  **What to do**:
  - `pip install strix-agent==<VERSION>` (pin exact version)
  - Pre-pull `ghcr.io/usestrix/strix-sandbox:1.0.0` via `docker pull` on worker startup
  - Verify image pull succeeds and stores in persistent volume
  - Add warmup script: pull image on worker boot (not on first scan)
  - Add pinned version to `requirements.txt` or worker Dockerfile
  - Verify `strix-agent` version in requirements (not latest — schema drift risk)

  **Must NOT do**:
  - Do not use `latest` tag or unpinned version
  - Do not pull image per-scan (pre-pull once, reuse)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: none

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with T10, T12)
  - **Blocks**: T13 (adapter calls `strix`)
  - **Blocked By**: T10 (worker must exist)

  **References**:
  - Strix PyPI: https://pypi.org/project/strix-agent/ — Version history
  - Strix GitHub: https://github.com/usestrix/strix — Docker image reference

  **Acceptance Criteria**:
  - [ ] `pip show strix-agent` returns pinned version
  - [ ] `docker images | grep strix-sandbox` shows 1.0.0
  - [ ] Image size logged (should be ~2-4GB)
  - [ ] Warmup script pulls image in <5 min on cold start

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Strix runs in non-interactive mode
    Tool: Bash (ssh into worker)
    Preconditions: Worker has Docker + Strix installed
    Steps:
      1. mkdir -p /tmp/strix-test-app && echo '{"name":"test"}' > /tmp/strix-test-app/package.json
      2. strix -n -m quick -t /tmp/strix-test-app --max-budget-usd 0.01
      3. Assert exit code 0 (no vulns expected on trivial app)
      4. Assert strix_runs/ directory created with run.json
    Expected Result: Strix runs headless, creates output directory
    Evidence: .omo/evidence/task-11-strix-headless.txt
  ```

  **Commit**: NO (infra)

---

- [~] 12. Worker egress allowlist + network rules

  **What to do**:
  - Configure worker egress: ALLOW Anthropic API (`api.anthropic.com:443`) + target app domain only
  - DENY all other outbound (Strix container probes external services — restrict to scan target)
  - Configure Caido proxy awareness (Strix routes all traffic through internal proxy on port 48080)
  - Test: Strix container can curl target app URL
  - Test: Strix container CANNOT reach `github.com` or other external sites (unless target is GitHub)
  - Add DNS resolution for sandbox-svc.internal inside Strix container

  **Must NOT do**:
  - Do not give full internet access (Strix nuclei/subfinder probe external — restrict)
  - Do not block Anthropic API (LLM calls must work)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: none
  - **Reason**: Network security rules with egress testing

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with T10, T11)
  - **Blocks**: T13
  - **Blocked By**: T10

  **References**:
  - `services/sandbox-svc/sandbox/network_rules.py` — Existing iptables pattern for egress control
  - Strix Dockerfile: `containers/Dockerfile` — Caido proxy configuration

  **Acceptance Criteria**:
  - [ ] Strix container can curl Anthropic API (200)
  - [ ] Strix container can curl target app URL (200)
  - [ ] Strix container CANNOT curl `https://github.com` (timeout/blocked)
  - [ ] Egress rules persist across Docker container restarts

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Egress allows LLM + target, blocks everything else
    Tool: Bash (ssh into worker)
    Preconditions: Egress rules applied
    Steps:
      1. docker run --rm ghcr.io/usestrix/strix-sandbox:1.0.0 curl -s -o /dev/null -w "%{http_code}" https://api.anthropic.com
      2. Assert HTTP 200 or 401 (connected, auth failed = OK — means rules allow traffic)
      3. docker run --rm ghcr.io/usestrix/strix-sandbox:1.0.0 curl -s --connect-timeout 5 https://github.com
      4. Assert timeout or connection refused (blocked)
    Expected Result: LLM API reachable, external sites blocked
    Evidence: .omo/evidence/task-12-egress-rules.txt
  ```

  **Commit**: NO (infra)

---

- [~] 13. StrixAdapter: subprocess wrapper + exit code handling

  **What to do**:
  - Create `services/sandbox-svc/sandbox/strix_adapter.py`
  - Async function: accepts repo path + sandbox URL + scan config → runs Strix → returns parsed findings
  - Subprocess call: `["strix", "-n", "-m", "standard", "-t", repo_path, "-t", sandbox_url, "--max-budget-usd", "0.40", "--instruction", instruction]`
  - Wall-clock timeout: `subprocess.run(timeout=1800)` — kill after 30min
  - Exit code handling: 0 → clean, 1 → error (log + fallback), 2 → success with findings
  - stdout captured but NOT logged raw (rich-formatted text, too noisy); log only scan summary lines
  - Working directory: `/tmp/antivibe-strix/{scan_id}/` — unique per scan
  - Run name collision: rename `strix_runs/<name>` to `{scan_id}` after completion

  **Must NOT do**:
  - Do not treat exit code 2 as error
  - Do not log raw stdout (contains colorful rich-formatted terminal output)
  - Do not use shared working directory (concurrent scans must not collide)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: none
  - **Reason**: Subprocess management, exit code handling, concurrency, timeout

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with T14)
  - **Blocks**: T16, T20
  - **Blocked By**: T10, T11, T12 (worker ready)

  **References**:
  - `strix/interface/main.py:817-820` — `-n` flag dispatches to `run_cli()`
  - `strix/core/runner.py:305` — `BudgetExceededError` handling
  - Python docs: https://docs.python.org/3/library/subprocess.html#subprocess.run

  **Acceptance Criteria**:
  - [ ] StrixAdapter.run() returns findings list on exit code 2
  - [ ] StrixAdapter.run() returns empty list on exit code 0
  - [ ] StrixAdapter.run() raises `StrixError` on exit code 1
  - [ ] 30min timeout kills process + logs timeout event
  - [ ] Unique working directory per scan_id (no collision)
  - [ ] `strix_runs/` directory renamed to scan_id after completion

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Strix finds vulnerabilities on vulnerable app
    Tool: interactive_bash (tmux)
    Preconditions: Strix worker running, vulnerable test app deployed
    Steps:
      1. cd services/sandbox-svc && python -c "
         from sandbox.strix_adapter import StrixAdapter
         adapter = StrixAdapter()
         findings = adapter.run(
             repo_path='/tmp/vuln-test-app',
             sandbox_url='https://test-sandbox.fly.dev',
             instruction='Test all API endpoints for BOLA/IDOR'
         )
         assert len(findings) > 0, f'Expected findings, got {len(findings)}'
         print(f'Found {len(findings)} vulnerabilities')
         "
      2. Assert output shows "Found N vulnerabilities" with N > 0
    Expected Result: Strix successfully finds and returns vulnerabilities
    Evidence: .omo/evidence/task-13-strix-findings.txt

  Scenario: Clean app returns no findings
    Tool: interactive_bash (tmux)
    Preconditions: Clean test app deployed (no vulnerabilities)
    Steps:
      1. Run StrixAdapter against clean app
      2. Assert findings list is empty (exit code 0)
    Expected Result: No false positives on clean code
    Evidence: .omo/evidence/task-13-strix-clean.txt

  Scenario: Timeout kills runaway scan
    Tool: interactive_bash (tmux)
    Preconditions: Strix adapter with timeout=10 set for testing
    Steps:
      1. Run scan against app that triggers long Strix run
      2. Assert process killed after 10s
      3. Assert log entry "scan timed out after 10s"
      4. Assert any partial findings are returned (not empty if Strix emitted any)
    Expected Result: Timeout enforced, partial results preserved
    Evidence: .omo/evidence/task-13-strix-timeout.txt
  ```

  **Commit**: YES
  - Message: `feat(strix): add StrixAdapter — subprocess wrapper with exit code handling + timeout`
  - Files: `services/sandbox-svc/sandbox/strix_adapter.py`

---

- [~] 14. Strix findings parser (vulnerabilities.json → AntiVibe schema)

  **What to do**:
  - Create `services/sandbox-svc/sandbox/strix_parser.py`
  - Read `strix_runs/{scan_id}/vulnerabilities.json` after adapter completes
  - Validate JSON schema before parse (check fields exist, types correct)
  - Map Strix schema → AntiVibe `Finding` type:
    - `id` → `external_id`
    - `title` → `title`
    - `severity` → `severity` (preserve: critical/high/medium/low/info)
    - `cvss` → `cvss_score` (float)
    - `cwe` → `cwe_id`
    - `cve` → `cve_id`
    - `endpoint` + `method` → `route` field
    - `description` → `description`
    - `poc_script_code` → `poc_curl` (encrypted — see T15)
    - `remediation_steps` → `remediation`
    - `code_locations` → `file_refs` [{file, start_line, end_line, snippet}]
    - `agent_name` → `source = "strix:{agent_name}"`
  - Filter: exclude findings where `code_locations[].file` starts with `node_modules/`, `.pnpm/`, `.git/`
  - Flag: mark all Strix findings with `ai_generated = true` in UI

  **Must NOT do**:
  - Do not import Strix as Python library (use only filesystem JSON)
  - Do not trust JSON format blindly — validate schema before parse
  - Do not store raw PoC scripts unencrypted (pass to T15)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: none
  - **Reason**: Schema mapping, validation, edge cases

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with T13, T15)
  - **Blocks**: T16 (merge needs parsed findings)
  - **Blocked By**: T13 (adapter produces JSON)

  **References**:
  - `packages/shared-types/src/index.ts` — AntiVibe Finding type definition
  - `strix/report/state.py:204-276` — Strix vulnerability report schema
  - Strix `vulnerabilities.json` example (from test run)

  **Acceptance Criteria**:
  - [ ] Parser validates JSON schema (rejects malformed JSON)
  - [ ] All Strix fields mapped to AntiVibe fields correctly
  - [ ] `node_modules/` findings filtered out
  - [ ] `ai_generated` flag set on all Strix findings
  - [ ] Empty findings.json → empty list (not error)

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Parse real Strix vulnerabilities.json
    Tool: interactive_bash (tmux)
    Preconditions: Strix output present in strix_runs/
    Steps:
      1. python sandbox/strix_parser.py --input strix_runs/test-scan/vulnerabilities.json
      2. Assert output is valid JSON array of AntiVibe Finding objects
      3. Assert each finding has required fields: title, severity, cvss_score, route, source
      4. Assert no findings have file paths starting with node_modules/
    Expected Result: Clean, validated AntiVibe finding list
    Evidence: .omo/evidence/task-14-parsed-findings.json

  Scenario: Malformed JSON returns clear error
    Tool: interactive_bash (tmux)
    Preconditions: Invalid JSON file created
    Steps:
      1. echo "not json" > /tmp/bad.json
      2. Run parser against /tmp/bad.json
      3. Assert error message "invalid JSON" (not traceback)
    Expected Result: Graceful validation error, no crash
    Evidence: .omo/evidence/task-14-bad-json.txt
  ```

  **Commit**: YES
  - Message: `feat(strix): add findings parser — vulnerabilities.json → AntiVibe schema with validation`
  - Files: `services/sandbox-svc/sandbox/strix_parser.py`

---

- [~] 15. PoC script encryption + secure storage

  **What to do**:
  - Encrypt `poc_script_code` field from Strix findings using AES-256-GCM
  - Encryption key: stored as Fly secret (`POC_ENCRYPTION_KEY`), never in code
  - Store encrypted blob in Supabase `findings.poc_encrypted` column (base64)
  - Decrypt only when user explicitly clicks "Reveal PoC" in dashboard
  - Add audit log: every decryption event logged with timestamp + user ID
  - Strip dangerous shell patterns from decrypted output before display (`rm -rf`, `curl | sh`, etc.)

  **Must NOT do**:
  - Do not store encryption key in source code
  - Do not store raw PoC scripts in Supabase
  - Do not decrypt without user action + audit log

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: none
  - **Reason**: Cryptography implementation, security-critical code

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with T14)
  - **Blocks**: T17 (report generator uses encrypted PoCs)
  - **Blocked By**: T14 (parser extracts PoC scripts)

  **References**:
  - Python cryptography library: https://cryptography.io/en/latest/
  - AES-GCM best practices: https://cryptography.io/en/latest/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM

  **Acceptance Criteria**:
  - [ ] PoC scripts encrypted before storage (verify ciphertext ≠ plaintext)
  - [ ] Decryption returns original script (round-trip test)
  - [ ] Wrong key → decryption fails with clear error (no crash)
  - [ ] Audit log written on every decryption
  - [ ] Dangerous patterns stripped from display output

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Round-trip encryption works
    Tool: interactive_bash (tmux)
    Preconditions: POC_ENCRYPTION_KEY set
    Steps:
      1. python -c "
         from sandbox.poc_encryption import encrypt, decrypt
         original = 'curl -X GET https://target.com/api/users/1 -H \"Authorization: Bearer fake\"'
         encrypted = encrypt(original)
         decrypted = decrypt(encrypted)
         assert original == decrypted, f'Round-trip failed'
         assert encrypted != original, 'Encrypted should differ from original'
         print('Round-trip OK')
         "
      2. Assert output "Round-trip OK"
    Expected Result: Encrypt + decrypt preserves original content
    Evidence: .omo/evidence/task-15-encryption-roundtrip.txt

  Scenario: Wrong key fails gracefully
    Tool: interactive_bash (tmux)
    Preconditions: Encrypted blob exists, wrong key used
    Steps:
      1. Attempt decrypt with wrong key
      2. Assert "decryption failed" error (not crash, not partial output)
    Expected Result: Clear error, no data leak
    Evidence: .omo/evidence/task-15-wrong-key.txt
  ```

  **Commit**: YES
  - Message: `feat(security): add AES-256-GCM PoC script encryption with audit-logged decryption`
  - Files: `services/sandbox-svc/sandbox/poc_encryption.py`

---

- [~] 16. Finding merge + dedup (Strix + Tier 1)

  **What to do**:
  - Create merge logic: combine Tier 1 findings + Strix findings into single list
  - Dedup key: (cwe, endpoint, method) — if both systems find same CWE on same route, keep highest CVSS
  - Dedup key fallback: (cwe, file, start_line) — for code-location matches
  - Sort merged list by CVSS descending
  - Mark source on each finding: `antivibe` or `strix`
  - Handle conflicts: Strix critical + Tier 1 medium on same endpoint → keep Strix critical, note "also found by static analysis"
  - Merge `code_locations` arrays when same file referenced

  **Must NOT do**:
  - Do not silently drop findings (every dedup logged)
  - Do not merge findings from different endpoints
  - Do not average CVSS scores (keep highest)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: none
  - **Reason**: Complex merge logic with edge cases

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (with T13, T14, T15)
  - **Blocks**: T17, T20
  - **Blocked By**: T14 (Strix parser), T5 (Tier 1 findings pipeline)

  **References**:
  - `packages/shared-types/src/index.ts` — Finding type definition
  - `services/sandbox-svc/scanner/tier1.py` — Existing finding dedup logic (reference pattern)

  **Acceptance Criteria**:
  - [ ] Same CWE + endpoint → single finding (highest CVSS kept)
  - [ ] Different endpoints → separate findings (no false merge)
  - [ ] Source field correctly set per finding
  - [ ] Merge log written (which findings were deduped, why)

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Duplicate findings merged correctly
    Tool: interactive_bash (tmux)
    Preconditions: Tier 1 finding + Strix finding for same CWE on same endpoint
    Steps:
      1. Run merge with test data: Tier 1 CWE-306 /api/users/{id} CVSS 7.5 + Strix CWE-306 /api/users/{id} CVSS 9.1
      2. Assert merged list has 1 finding (not 2)
      3. Assert merged CVSS = 9.1 (highest kept)
      4. Assert source = "strix" (or both noted)
    Expected Result: Single finding with highest severity preserved
    Evidence: .omo/evidence/task-16-dedup-merge.json

  Scenario: Different endpoints NOT merged
    Tool: interactive_bash (tmux)
    Preconditions: Tier 1 finding on /api/users + Strix finding on /api/orders (same CWE)
    Steps:
      1. Run merge
      2. Assert merged list has 2 findings (different endpoints = separate)
    Expected Result: No false merge of different routes
    Evidence: .omo/evidence/task-16-no-false-merge.json
  ```

  **Commit**: YES
  - Message: `feat(pipeline): add Strix + Tier 1 finding merge with CWE-endpoint dedup`
  - Files: `services/sandbox-svc/sandbox/finding_merge.py`

---

- [~] 17. Updated report generator (Strix findings w/ source tag)

  **What to do**:
  - Extend existing report generator to handle merged findings from both sources
  - Add `source` badge: `[antivibe]` vs `[strix]` in report
  - Add `ai_generated` disclaimer for Strix findings ("This finding was identified by an AI agent and may require human verification")
  - Include CVSS score + CWE reference in report
  - Strix code_locations → code snippets with fix_before/fix_after
  - Generate Markdown executive summary + JSON "FixIt receipt"

  **Must NOT do**:
  - Do not present Strix findings as authoritative (always flag as AI-generated)
  - Do not skip CVSS/CWE fields (they add credibility)

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: none
  - **Reason**: Report generation with structured output

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 6 (with T18, T19)
  - **Blocks**: T20
  - **Blocked By**: T16 (merged findings), T15 (encrypted PoCs)

  **References**:
  - `services/sandbox-svc/sandbox/report_generator.py` — Existing report generator (if built)
  - Strix `penetration_test_report.md` format — reference for structure

  **Acceptance Criteria**:
  - [ ] Report includes both antivibe and strix findings with source badges
  - [ ] Strix findings marked with AI disclaimer
  - [ ] CVSS + CWE fields rendered correctly
  - [ ] code_locations with fix_before/fix_after rendered
  - [ ] Report generated in <5s for 100 findings

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Report shows both sources
    Tool: interactive_bash (tmux)
    Preconditions: Merged findings with both sources
    Steps:
      1. Generate report from merged findings
      2. Assert report contains "[antivibe]" badge on Tier 1 findings
      3. Assert report contains "[strix]" badge on Strix findings
      4. Assert AI disclaimer present on Strix findings
    Expected Result: Clear source attribution in report
    Evidence: .omo/evidence/task-17-source-badges.md
  ```

  **Commit**: YES
  - Message: `feat(report): add Strix findings to report with source badges + AI disclaimer`
  - Files: `services/sandbox-svc/sandbox/report_generator.py`

---

- [~] 18. Updated auto-PR writer (Strix code_locations)

  **What to do**:
  - Extend auto-PR writer to include Strix `code_locations` with fix_before/fix_after
  - Generate diff patches from Strix code_locations (actual code changes)
  - PR description: include source badge per finding, CVSS score, CWE reference
  - Branch name: `antivibe/fix-{scan_id}`
  - Commit message: include source + severity
  - PR label: `antivibe` + severity label (`critical`, `high`, etc.)
  - NEVER auto-merge (existing policy)

  **Must NOT do**:
  - Do not auto-merge (human review mandatory)
  - Do not apply fix patches from Strix blindly (review required)
  - Do not commit if no findings have code_locations

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: none
  - **Reason**: Git operations + patch generation + GitHub API

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 6 (with T17, T19)
  - **Blocks**: T20
  - **Blocked By**: T16 (needs findings with code_locations)

  **References**:
  - GitHub API: https://docs.github.com/en/rest/pulls/pulls
  - `services/sandbox-svc/sandbox/auto_pr.py` — Existing PR writer (if built)

  **Acceptance Criteria**:
  - [ ] PR created with Strix code_locations as diff patches
  - [ ] Branch named correctly: `antivibe/fix-{scan_id}`
  - [ ] PR description includes CVSS + CWE + source badge
  - [ ] PR not auto-merged
  - [ ] No PR created if no code_locations in findings

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: PR created with Strix patches
    Tool: Bash (git + gh CLI)
    Preconditions: Test repo with security issues, GitHub token configured
    Steps:
      1. Run auto-PR writer with Strix findings that have code_locations
      2. gh pr list --repo test-org/test-repo → assert PR exists
      3. gh pr view → assert description contains "strix" source badge
      4. Assert PR has label "antivibe"
      5. Assert PR is NOT merged (open state)
    Expected Result: PR opened with patches, not merged
    Evidence: .omo/evidence/task-18-pr-created.txt
  ```

  **Commit**: YES
  - Message: `feat(pr): add Strix code_locations to auto-PR with source badges + CVSS`
  - Files: `services/sandbox-svc/sandbox/auto_pr.py`

---

- [~] 19. Dashboard: findings source badges (antivibe vs strix)

  **What to do**:
  - Add `source` badge to finding cards in dashboard: `[antivibe]` (blue) vs `[strix]` (purple)
  - Add AI disclaimer tooltip for Strix findings: hover shows "AI-generated finding — may require verification"
  - Filter by source: dropdown "All sources / AntiVibe only / Strix only"
  - Sort findings by source + CVSS
  - "Reveal PoC" button decrypts and shows PoC script (with audit log from T15)

  **Must NOT do**:
  - Do not show decrypted PoC without user action (click required)
  - Do not show raw encrypted blob in UI

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
  - **Skills**: none
  - **Reason**: UI polish with badges, tooltips, filters

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 6 (with T17, T18)
  - **Blocks**: None (endpoint)
  - **Blocked By**: T6 (dashboard exists), T16 (source field on findings)

  **References**:
  - `apps/dashboard/src/` — Existing finding detail components
  - `packages/shared-types/src/index.ts` — Finding.source field

  **Acceptance Criteria**:
  - [ ] Source badge visible on each finding card
  - [ ] Badge colors distinct (blue for antivibe, purple for strix)
  - [ ] Source filter dropdown works (All / AntiVibe / Strix)
  - [ ] AI disclaimer tooltip shows on hover for Strix findings
  - [ ] "Reveal PoC" decrypts and shows script (on click, not on load)

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Source badges visible and filterable
    Tool: Playwright
    Preconditions: Scan with both antivibe and strix findings
    Steps:
      1. Navigate to scan detail page
      2. Assert at least one finding has "[antivibe]" badge (blue)
      3. Assert at least one finding has "[strix]" badge (purple)
      4. Click filter dropdown → "Strix only"
      5. Assert only Strix findings visible
      6. Take screenshot
    Expected Result: Badges + filter work correctly
    Evidence: .omo/evidence/task-19-source-badges.png

  Scenario: AI disclaimer tooltip
    Tool: Playwright
    Preconditions: Strix findings in list
    Steps:
      1. Hover over "[strix]" badge
      2. Assert tooltip appears: "AI-generated finding — may require verification"
      3. Take screenshot of tooltip
    Expected Result: Disclaimer visible on hover
    Evidence: .omo/evidence/task-19-ai-disclaimer.png

  Scenario: Reveal PoC decrypts on click
    Tool: Playwright
    Preconditions: Strix finding with encrypted PoC
    Steps:
      1. Navigate to finding detail
      2. Assert PoC section shows "Click to reveal" button (not raw curl)
      3. Click "Reveal PoC"
      4. Assert curl command appears (decrypted)
      5. Take screenshot
    Expected Result: PoC hidden by default, revealed on click
    Evidence: .omo/evidence/task-19-reveal-poc.png
  ```

  **Commit**: YES
  - Message: `feat(dashboard): add source badges + AI disclaimer + PoC reveal for Strix findings`
  - Files: `apps/dashboard/src/`

---

- [~] 20. End-to-end Strix scan integration svc

  **What to do**:
  - Wire everything together: scan orchestrator → Tier 1 → Tier 2 → Strix Adapter → parser → merge → report → PR
  - Handle partial failures: Strix fails → return Tier 1 + Tier 2 findings (graceful degradation)
  - Handle Strix timeout: return partial findings + "scan timed out" status
  - Cost tracking: separate LLM cost for Tier 1 + Strix (total must be ≤$0.50)
  - Scan status transitions: queued → tier1 → tier2 → strix → merging → reporting → completed
  - Circuit-breaker covers ALL LLM calls (Tier 1 + Strix combined)

  **Must NOT do**:
  - Do not hard-require Strix success (pipeline continues with partial results)
  - Do not exceed $0.50 total across all tiers

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: none
  - **Reason**: Complex orchestration with error recovery

  **Parallelization**:
  - **Can Run In Parallel**: NO (integration — depends on all components)
  - **Parallel Group**: Wave 6 (sequential)
  - **Blocks**: T21, T22
  - **Blocked By**: T13, T16, T17, T18

  **References**:
  - `services/sandbox-svc/scanner/tier1.py` — Tier 1 orchestrator pattern
  - `services/sandbox-svc/sandbox/strix_adapter.py` — Strix adapter
  - `services/sandbox-svc/sandbox/finding_merge.py` — Merge logic

  **Acceptance Criteria**:
  - [ ] Full pipeline: GitHub URL → Tier 1 → Tier 2 → Strix → merged report → PR
  - [ ] Strix failure → Tier 1+2 results returned (graceful degradation)
  - [ ] Total LLM cost <$0.50 verified per scan
  - [ ] Scan status transitions correct across all stages

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Full pipeline runs end-to-end with Strix
    Tool: Bash (curl) + Playwright (dashboard)
    Preconditions: All services running
    Steps:
      1. Submit scan of vulnerable test repo
      2. Poll status until "completed"
      3. Assert findings contain both antivibe and strix sources
      4. Open dashboard, assert all findings visible with source badges
      5. Assert PR created on test repo (if code_locations present)
    Expected Result: Complete pipeline delivers merged results
    Evidence: .omo/evidence/task-20-e2e-strix.json

  Scenario: Strix failure → pipeline continues
    Tool: Bash (curl)
    Preconditions: Strix worker unreachable (simulated)
    Steps:
      1. Submit scan
      2. Assert scan status "completed" (not "failed")
      3. Assert findings contain Tier 1 results
      4. Assert log entry "Strix unavailable — skipping Tier 3 fuzzing"
    Expected Result: Graceful degradation, not total failure
    Evidence: .omo/evidence/task-20-strix-failover.txt
  ```

  **Commit**: YES
  - Message: `feat(pipeline): integrate Strix fuzzing into end-to-end scan with graceful degradation`
  - Files: `services/sandbox-svc/sandbox/scan_orchestrator.py`

---

- [~] 21. Strix worker cleanup (purge, watchdog, prune)

  **What to do**:
  - After each scan: `rm -rf /tmp/antivibe-strix/{scan_id}/`
  - Docker container cleanup: `docker rm -f <container>` (Strix auto-cleans but add fallback)
  - Disk watchdog: cron job checks `strix_runs/` disk usage, purges directories older than 24h
  - Docker image prune: `docker image prune -a --filter "until=24h"` daily
  - Stale container killer: find + kill Strix containers running >30min
  - Add NOTICE file to repo root (Apache-2.0 requirement for Strix)

  **Must NOT do**:
  - Do not prune active scan directories
  - Do not delete Docker image while scan is running
  - Do not forget Apache-2.0 NOTICE file

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: none
  - **Reason**: Cleanup scripts, cron, disk management

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on T20)
  - **Parallel Group**: Wave 7 (sequential)
  - **Blocks**: None
  - **Blocked By**: T20 (need pipeline to know cleanup targets)

  **References**:
  - Strix LICENSE: https://github.com/usestrix/strix/blob/main/LICENSE
  - Docker prune docs: https://docs.docker.com/engine/reference/commandline/image_prune/

  **Acceptance Criteria**:
  - [ ] Scan directory deleted after findings uploaded to Storage
  - [ ] Stale containers killed after 30min (if any)
  - [ ] `docker image prune` runs daily via cron
  - [ ] NOTICE file present in repo root with Apache-2.0 text

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Scan cleanup after completion
    Tool: Bash (ssh into worker)
    Preconditions: Completed scan with strix_runs/
    Steps:
      1. Check /tmp/antivibe-strix/ before scan → directory exists
      2. Run cleanup after findings uploaded
      3. Assert /tmp/antivibe-strix/{scan_id}/ no longer exists
      4. Assert Docker container for this scan is gone
    Expected Result: No disk leaks after scan
    Evidence: .omo/evidence/task-21-cleanup.txt

  Scenario: NOTICE file present
    Tool: Bash
    Preconditions: NOTICE file committed
    Steps:
      1. cat NOTICE | head -5
      2. Assert contains "Apache-2.0" and "Strix" mention
    Expected Result: License notice properly attributed
    Evidence: .omo/evidence/task-21-notice.txt
  ```

  **Commit**: YES
  - Message: `chore(strix): add cleanup watchdog + NOTICE file (Apache-2.0 attribution)`
  - Files: `services/sandbox-svc/sandbox/cleanup.py`, `NOTICE` (root)

---

- [~] 22. Benchmark + FP validation on fixture repos

  **What to do**:
  - Run 5+ fixture repo scans through full Strix pipeline
  - Measure: FP rate (<10%), detection rate (>80% for known vulns), latency, cost
  - Categories: 2 known-vulnerable repos, 2 clean repos, 1 mixed
  - Compare Strix findings vs Tier 1 findings (what does Strix find that we miss?)
  - Document: which vuln classes Strix catches well vs poorly
  - Tune `--max-budget-usd` and `--scan-mode` based on benchmark results

  **Must NOT do**:
  - Do not benchmark against repos you don't own (use fixture repos from old plan Wave 7)
  - Do not publish findings from vulnerable fixture repos

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: none
  - **Reason**: Benchmark testing with manual analysis

  **Parallelization**:
  - **Can Run In Parallel**: NO (sequential benchmarks)
  - **Parallel Group**: Wave 7 (sequential)
  - **Blocks**: None
  - **Blocked By**: T20 (pipeline must work)

  **References**:
  - Old plan Wave 7 fixture repos (T45-T46)
  - `services/sandbox-svc/tests/` — Existing test patterns

  **Acceptance Criteria**:
  - [ ] 5 fixture scans complete
  - [ ] FP rate <10% across all scans
  - [ ] Detection rate >80% for known vulns in fixture repos
  - [ ] Cost per scan averaged and documented
  - [ ] Benchmark results documented in `docs/benchmark-strix.md`

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Strix detects known vulnerabilities in fixture repos
    Tool: Bash (curl)
    Preconditions: Fixture repos with known vulns deployed
    Steps:
      1. Scan 2 known-vulnerable fixture repos
      2. For each: assert findings count > 0
      3. Assert at least 1 finding matches known vuln in fixture spec
      4. Log FP count (findings not in fixture spec)
      5. Calculate detection rate: found / total_known
    Expected Result: >80% of known vulns detected, <10% FP
    Evidence: .omo/evidence/task-22-benchmark.json

  Scenario: Clean repos produce minimal findings
    Tool: Bash (curl)
    Preconditions: Clean fixture repos deployed
    Steps:
      1. Scan 2 clean fixture repos
      2. Assert findings count = 0 (or all low-severity with clear explanation)
      3. Calculate FP rate
    Expected Result: Zero false positives on clean code
    Evidence: .omo/evidence/task-22-clean-benchmark.json
  ```

  **Commit**: NO (testing/documentation)

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**

- [~] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Check evidence files exist in .omo/evidence/. Verify Phase Gate conditions met before Phase 2 tasks started.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | Phase Gate [PASS/FAIL] | VERDICT: APPROVE/REJECT`

- [~] F2. **Code Quality Review** — `unspecified-high`
  Run `python -m pytest tests/ -v` + `pnpm -r test`. Review all changed files for: empty catches, console.log, commented-out code, unused imports. Check AI slop. Verify NOTICE file present. Verify `strix-agent` version pinned.
  Output: `Build [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [~] F3. **Real Manual QA** — `unspecified-high` (+ `playwright` skill)
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration. Test: Phase 1 pipeline → Phase 2 Strix pipeline → dashboard → report → PR flow. Test graceful degradation (Strix down → Tier 1 still works).
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [~] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built, nothing beyond spec. Check "Must NOT do" compliance. Verify Phase Gate was enforced (check git log — Phase 2 tasks started AFTER Phase 1 complete).
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Phase Gate Enforced [YES/NO] | VERDICT`

---

## Commit Strategy

**Phase 1 commits:**
- `feat(pipeline): wire end-to-end scan orchestrator — GitHub URL → Tier 1 → Tier 2 → Supabase`
- `feat(dashboard): add scan list + finding detail views with Supabase integration`
- `test(pipeline): validate circuit-breaker behavior + cost tracking accuracy`
- `feat(web): add landing page + Stripe $29/mo checkout + free tier email gate`

**Phase 2 commits (GATED):**
- `feat(strix): add StrixAdapter — subprocess wrapper with exit code handling + timeout`
- `feat(strix): add findings parser — vulnerabilities.json → AntiVibe schema with validation`
- `feat(security): add AES-256-GCM PoC script encryption with audit-logged decryption`
- `feat(pipeline): add Strix + Tier 1 finding merge with CWE-endpoint dedup`
- `feat(report): add Strix findings to report with source badges + AI disclaimer`
- `feat(pr): add Strix code_locations to auto-PR with source badges + CVSS`
- `feat(dashboard): add source badges + AI disclaimer + PoC reveal for Strix findings`
- `feat(pipeline): integrate Strix fuzzing into end-to-end scan with graceful degradation`
- `chore(strix): add cleanup watchdog + NOTICE file (Apache-2.0 attribution)`

---

## AGENTS.md Update (To Enforce Phase Gate)

The following block must be inserted into the repo's `AGENTS.md` (or created if it doesn't exist):

```markdown
## PHASE 2 GATE — CRITICAL

Reference plan: `.omo/plans/antivibe-mvp-and-strix.md`

Phase 2 (Strix Integration, tasks T10-T22) is STRICTLY BLOCKED until ALL of:
1. [ ] Phase 1 tasks T1-T9 all marked `[x]` complete in plan file
2. [ ] At least 3 real repos scanned end-to-end successfully (verify in dashboard)
3. [ ] Dashboard publicly accessible at production URL with scan results visible
4. [ ] Zero unhandled errors in production logs for 48+ consecutive hours
5. [ ] At least 1 real user feedback collected and documented

**If ANY condition fails: STOP. Do not start Phase 2. Return to Phase 1 fixes.**
**If all conditions pass: Document in plan file, then begin T10.**
```

---

## Success Criteria

### Phase 1 Verification Commands
```bash
# Infrastructure health
curl https://<dashboard>.fly.dev/health          # Expected: 200
curl http://sandbox-svc.internal:8080/health      # Expected: 200

# End-to-end scan
curl -X POST http://sandbox-svc.internal:8080/scan \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/hasnainzxc/test-nextjs-app"}'  # Expected: 202

# Tests pass
cd services/sandbox-svc && python -m pytest tests/ -v  # Expected: 392 passed
cd ../.. && pnpm -r test                                 # Expected: 12 passed
```

### Phase 2 Verification Commands (GATED)
```bash
# Strix worker ready
fly ssh console -a antivibe-strix-worker -c "strix --version"  # Expected: version string
fly ssh console -a antivibe-strix-worker -c "docker ps"         # Expected: empty list (0 running)

# Strix adapter test
cd services/sandbox-svc && python -c "
from sandbox.strix_adapter import StrixAdapter
adapter = StrixAdapter()
findings = adapter.run('/tmp/vuln-test-app', 'https://test.fly.dev', 'Test BOLA')
assert isinstance(findings, list)
print(f'Strix adapter: OK — returned {len(findings)} findings')
"  # Expected: OK with findings count
```

### Future — Stack Expansion (Post-Phase 2)

Tasks to add stack coverage for repos that don't match the current 6-stack whitelist.
Unblocks scanning repos like `hasnainzxc/dropin` (vanilla JS/HTML) and `vite` projects.

| Task | Stack | Changes Required | Difficulty |
|------|-------|-----------------|------------|
| S1 | Vite | `detect_stack.py`: check `vite.config.*`; `containerize.py`: `vite preview`; `ast_parser.py`: Vite parser | Medium |
| S2 | Vanilla HTML/JS | `detect_stack.py`: fallback when `index.html` + `package.json`; no sandbox (Tier 1 only) | Easy |
| S3 | Python Monorepo | `detect_stack.py`: multi-stack detection; monorepo layout analysis | Medium |
| S4 | Nuxt.js | `detect_stack.py`: check `nuxt.config.*` + `nuxt` dep; containerize Nuxt build | Medium |
| S5 | Django | `detect_stack.py`: check `manage.py` + `settings.py`; containerize with gunicorn | Medium |
| S6 | Generic Python | `detect_stack.py`: fallback for any Python project with `requirements.txt` | Easy |

### Final Checklist
- [ ] Phase Gate conditions met before Phase 2 (verified in F4)
- [ ] All "Must Have" features shipped (verified in F1)
- [ ] All "Must NOT Have" features absent (verified in F1, F4)
- [ ] All tests pass (verified in F2)
- [ ] All QA scenarios executed with evidence (verified in F3)
- [ ] Strix NOTICE file present
- [ ] Strix agent version pinned in requirements
- [ ] PoC scripts encrypted at rest
- [ ] Worker egress allowlist enforced

