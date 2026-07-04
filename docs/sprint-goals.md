# AntiVibe — Sprint Goals

**Purpose:** 16-20 week roadmap for solo-founder YC-tier build. Each sprint = 2 weeks with explicit exit criteria + lifeboat fallback.
**Last Updated:** 2026-07-04
**Owner:** AntiVibe solo-founder

## Lifecycle

- **Sprint cadence**: 2 weeks
- **Demo Day fallback**: If behind schedule at Sprint 2 exit (W4), freeze Tier 2+3 development and ship Tier 1 only as YC demo
- **Sprint exit criteria** (all required): unit tests green + QA scenarios captured + evidence dir updated + plan tasks checked + code-review approval (or self-review w/ detailed record)
- **Pre-sprint planning**: Pick tasks from `.omo/plans/antivibe-saas.md`, update `## Current Sprint` section below, mark in_progress in plan
- **Post-sprint retro**: Update status tables in this doc + cross-doc status sections (architecture.md, system-design.md)

## Week-by-Week Plan

| Week | Goal | Ships To | Lifeboat | Exit Criteria |
|------|------|---------|----------|---------------|
| W1 | Wave 1 — scaffold + Supabase + Fly client + 10-doc suite | dev local | None (foundational) | `pnpm dev` boots; docs/ has 11 files; `pytest sandbox-svc/init` green |
| W2 | Wave 1 cont + Tier 1 cloner + stack detector | dev local | Defer rate limiter to W3 | `git clone --depth 1` works on test repo; stack detect 90%+ on 6 fixtures |
| W3 | Tier 1 AST parser + secret detector | dev local | Skip entropy detector (regex-only v1) | 6-stack route extraction; FP rate on clean fixtures = 0 |
| W4 | Tier 1 config-flaw + LLM extractor + orchestrator | internal beta on own repos | **DEMO DAY GATE** — if behind, freeze Tier 2+3 | Tier 1 scan end-to-end on fixtures; p95 <5min; cost <$0.10 |
| **Demo Day Gate (W4)** | **If ship-to-YC-quality is at risk, freeze Tier 2+3. Polish Tier 1 only. Pitch = "static scan + LLM semantic explanation"** | — | — | — |
| W5 | Tier 2: containerizer + mock DB seeder | dev local | Skip Firestore emulator; Postgres-only Tier 2 | Containerize 6 stacks; seed 10 fake users |
| W6 | Tier 2: sandbox spin-up + route mapper | dev local | Use Docker on Fly Machines w/o Firecracker direct | Fly Machine boots <30s; routes extracted ≥95% match fixture truth |
| W7 | Tier 2: JWT forge (NextAuth + Firebase first 2 adapters) | dev local | Defer Clerk + custom to W8 | JWT forge for 2 adapters; BOLA PoC on fixture |
| W8 | Tier 2: JWT forge cont (Clerk + Supabase + custom) + health monitor + orchestrator | internal beta | Cut Clerk if slow | All 5 adapters; sandbox destroy on completion verified |
| W9 | Tier 3: route walker | dev local | Static route list (no traversal) | All routes walked w/ baseline coverage |
| W10 | Tier 3: BOLA tester + no-stop pivot v1 | dev local | Pivot only on adjacent paths (skip method/param swap) | BOLA on fixture produces PoC capture |
| W11 | Tier 3: OSS inference client + dual-model orchestrator | dev local | Use GPT-4o instead of Llama-3-70B if OSS quality <80% | Cost ledger per scan; TTFT <3s |
| W12 | Tier 3: no-stop pivot v2 (method swap + param swap + token swap) + orchestrator | internal beta | Defer param swap to post-launch | All 4 pivot vectors active; 200-attempt cap enforced |
| W13 | Wave 5: report generator + remediation code generator | dev local | Hardcode remediation snippets for Top-10 finding types | Markdown report + diff patches produced |
| W14 | Wave 5: auto-PR writer + GitHub OAuth App + webhook handler + dashboard scan-list view | internal beta | Skip webhook; manual trigger only | Auto-PR opened on test vuln repo (never auto-merged) |
| W15 | Wave 5 cont + Wave 6: billing + subscription gating + cost tracker + circuit-breaker | dev local | Flat-tier $29/mo (skip Indie vs Pro split) | Stripe webhook → Supabase update working |
| W16 | Wave 6: scan email delivery + E2E scan integration svc + dashboard billing view | dev local | Plain-text email (skip HTML) | Full URL submission journey green on Postman |
| W17 | Wave 7: vulnerable fixture repos (5) + clean fixture repos (5) | dev local | 4+4 instead of 5+5 | Fixtures tagged + committed |
| W18 | Wave 7: benchmark runner + Playwright E2E suite | internal beta | Skip >50 repos benchmark; run on 20 | Playwright green: land→submit→wait→view→upgrade→webhook→view-all |
| W19 | YC demo script + screen recording + pre-launch hardening | YC pitch-ready | Pre-record demo video (live demo risk) | Demo MP4 <3min; hash test on /docs suite pass |
| W20 | Demo Day pitch dry-run + cleanup + moral support polish | YC Demo Day | Cancel if Mission failed (won't happen) | Pitch delivery practiced 5x; QA gate green |

## Current Sprint

**Active sprint**: Sprint 0 — Pre-build (documentation + planning phase)
**Start**: 2026-07-04
**End**: ongoing (no fixed end; segues into Wave 1 once /start-work is invoked)

**Sprint goals**:
- [x] Plan generation (`.omo/plans/antivibe-saas.md`) — in progress
- [x] Doc suite scaffolding (`/docs/*.md`) — in progress
- [ ] Per-feature docs (`/docs/features/*.md`) — pending
- [ ] Repo scaffold via Task 1 (Wave 1)
- [ ] Supabase project created via Task 3
- [ ] Fly Machines client via Task 5

**Progress markers**:
- Plan draft: complete in `.omo/drafts/antivibe-saas.md`
- Plan file: in progress at `.omo/plans/antivibe-saas.md` (~14 of 50 tasks written)
- Topical docs (architecture/system-design/etc.): being created THIS sprint

## Done Definition (per sprint)

A sprint is "Done" when ALL of:
- [ ] All planned task boxes checked in `.omo/plans/antivibe-saas.md`
- [ ] Unit tests green (`pytest` + `vitest`)
- [ ] Lint clean (ruff + eslint)
- [ ] QA scenario evidence files saved in `.omo/evidence/task-{N}-{slug}.{ext}`
- [ ] Feature docs (if any new module shipped) added under `/docs/features/{slug}.md`
- [ ] `## Status` section in this doc updated
- [ ] Cross-doc status sections in `architecture.md` + `system-design.md` updated
- [ ] Builds pass: `pnpm -r build && pytest`
- [ ] (W14+) Playwright E2E green

## Sprint Exit Criteria Check (mirror Metis metrics)

- FP rate <5% on benchmark set (verified at W18)
- Stack-detect accuracy >90% on 50 fixtures (verified at W18)
- Tier 1 p95 latency <5min (verified at W4)
- Tier 2+3 p95 latency <15min (verified at W12)
- Cost per scan <$0.50 (verified at W18 via benchmark)
- LLM token usage <100K/scan (verified at W18)

## Lifeboat Decision Tree

- **If W4 Demo Day Gate trips** → ship Tier 1 only as "static scan + LLM explanation", defer Tier 2+3 to v1.1
- **If W8 sandbox unstable** → use Docker-on-Fly without Firecracker direct, 30s boot acceptable
- **If W10 BOLA test unreliable** → ship static + sandbox-spin-up (no fuzzing), pitch as "sandbox observability + auto-PR for static findings"
- **If W14 auto-PR flaky** → ship static report + manual PR (manual playwright-style click-through)
- **If W18 benchmark FP >5%** → push back launch 2 wks; tune secret detector + config-flaw analyzer
- **If W20 not pitch-ready** → defer YC; ship as direct B2B w/ 5 closed pilots