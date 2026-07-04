# AntiVibe — Per-Feature Docs Index

**Purpose:** Catalog of every feature module in AntiVibe. Each gets its own doc under `docs/features/{feature-slug}.md`. Updated as features ship.
**Last Updated:** 2026-07-04
**Owner:** AntiVibe solo-founder + coding agents (each feature doc owned by the implementation task listed below)

Follow the template in `docs/agent-orchestration.md#per-feature-doc-template` (under "Per-Feature Doc Discipline" section in `.omo/plans/antivibe-saas.md`).

## Status Legend
- [ ] Pending — task not started
- [~] In Progress — task dispatched
- [x] Shipped — feature doc linked below

## Wave 1 — Foundation

- [ ] repo-scaffold — Task 1 — Next.js monorepo + Tailwind + shadcn/ui
- [ ] doc-suite-topical — Task 2 — 10 topical docs (architecture/system-design/etc.) + this index
- [ ] supabase-schema — Task 3 — Supabase project + schema + RLS
- [ ] shared-types — Task 4 — TS types package
- [ ] fly-machines-client — Task 5 — Fly Machines async client Python
- [ ] blob-storage-client — Task 6 — Supabase Storage client (TS + Python)
- [ ] rate-limiter-email-gate — Task 7 — middleware rate limit + email verification
- [ ] ci-test-infra — Task 8 — vitest + pytest + playwright + GH Actions

## Wave 2 — Tier 1 Static Engine

- [ ] repo-cloner — Task 9 — secure clone (--depth 1, no LFS, 500MB cap, no postinstall)
- [ ] stack-detector — Task 10 — heuristic 6-stack whitelist
- [ ] ast-parser — Task 11 — per-stack AST + route extractor + env finder
- [ ] secret-detector — Task 12 — regex + entropy + FP-control
- [ ] config-flaw-analyzer — Task 13 — Firestore rules + IAM + CORS + permissive auth
- [ ] llm-extractor — Task 14 — Anthropic Claude client w/ input sanitization
- [ ] tier1-orchestrator — Task 15 — chain clone→detect→ast→analyzers w/ circuit-breaker

## Wave 3 — Tier 2 Sandbox

- [ ] app-containerizer — Task 16 — per-stack Dockerfile generator
- [ ] mock-db-seeder — Task 17 — Postgres + Firestore emulator seed 10 fake users across 2 tenants
- [ ] sandbox-spinup — Task 18 — Fly Machines spin-up + egress DENY ALL + auto-destroy
- [ ] route-mapper — Task 19 — per-stack route index
- [ ] jwt-forge — Task 20 — 5 forge adapters (NextAuth/Clerk/Firebase/Supabase/custom)
- [ ] sandbox-health-monitor — Task 21 — boot detect + log stream + crash recovery
- [ ] tier2-orchestrator — Task 22 — chain containerize→seed→spin→forge→pass-to-Tier-3

## Wave 4 — Tier 3 Fuzz Agent

- [ ] route-walker — Task 23 — iterate routes w/ stateful queue
- [ ] bola-tester — Task 24 — param swap + token swap cross-tenant
- [ ] no-stop-pivot-engine — Task 25 — 403/404 → adjacent + method-swap + header-fuzz
- [ ] oss-inference-client — Task 26 — Together/Anyscale no-refusal protocol
- [ ] dual-model-orchestrator — Task 27 — commercial extraction + OSS fuzz-pattern gen
- [ ] poc-capture-log-sink — Task 28 — curl repro + status diff + log sink
- [ ] tier3-orchestrator — Task 29 — chain walker→tester→pivot→model→capture→emit findings

## Wave 5 — Reporting + GitHub + Dashboard

- [ ] finding-normalizer — Task 30 — dedup + severity + CVSS-ish scoring
- [ ] exec-report-generator — Task 31 — markdown + JSON "FixIt receipt"
- [ ] remediation-code-generator — Task 32 — per-finding diff snippet
- [ ] auto-pr-writer — Task 33 — branch + commit + open PR (NEVER auto-merge)
- [ ] github-oauth-app — Task 34 — OAuth App flow + token store + scope mgmt
- [ ] webhook-handler — Task 35 — GitHub webhook w/ HMAC-SHA256 verify + push-triggered scan
- [ ] dashboard-scan-list — Task 36 — Next.js scan-list view (auth-gated)
- [ ] dashboard-finding-detail — Task 37 — per-scan drill + PoC replay + remediation code

## Wave 6 — Billing + Integration + Lifecycle

- [ ] billing-integration — Task 38 — Stripe/LemonSqueezy + webhook → Supabase
- [ ] subscription-gating — Task 39 — quota enforcement (free=1, indie/pro unlimited)
- [ ] scan-cost-tracker — Task 40 — Fly Machine seconds + LLM tokens → per-scan $ ledger
- [ ] circuit-breaker — Task 41 — 10min timeout + token cap + abort-and-report-partial
- [ ] scan-email-delivery — Task 42 — post-scan email + welcome + billing emails
- [ ] e2e-scan-integration — Task 43 — URL intake → run all 3 tiers → report → auto-PR → email
- [ ] dashboard-billing-view — Task 44 — dashboard billing + usage meter

## Wave 7 — Test Harness + Fixtures + YC Demo Prep

- [ ] vulnerable-fixtures — Task 45 — 5 deliberately-vulnerable repos (1 per stack)
- [ ] clean-fixtures — Task 46 — 5 deliberately-clean repos (FP-control set)
- [ ] benchmark-runner — Task 47 — measure FP<5%, detect>90%, p95, cost
- [ ] playwright-e2e-suite — Task 48 — full user journey E2E (land→submit→wait→view→upgrade→webhook→view-all)
- [ ] yc-demo-recording — Task 49 — Demo Day recording (BOLA + auto-PR landing)
- [ ] pre-launch-hardening — Task 50 — secrets-log audit + egress audit + prompt-injection tests

## Per-Feature Doc Template (mandatory)

```md
# Feature: <Human Name>

**Purpose:** <one-sentence>
**Wave:** <N>  **Owner task:** <#>  **Status:** shipped | in_progress | blocked

## Public API
<signatures, types, exported symbols>

## Internal flow
<Mermaid sequence OR numbered steps>

## Inputs
<types + sources>

## Outputs
<types + sinks>

## Acceptance criteria
<mirror from plan task's Acceptance Criteria>

## Test plan
<mirror from plan task's QA Scenarios>

## Cross-references
<links to topical docs e.g. [see architecture.md#tier-pipeline], [see system-design.md#jwt-forge-spec]>

## Changelog
| Date | Change |
|------|--------|
| <ISO> | Initial |
```

**Discipline rules**:
- Cap ≤ 800 words per feature doc
- Each Wave 2+ implementation task's "Files" line MUST include `docs/features/{slug}.md`
- Per-feature doc PR is coupled with the code PR (atomic)
- Failure to ship a feature doc = task incomplete (F1+F4 will reject)
- No duplicating content from topical docs — CROSS-REF instead