# AntiVibe — Agent Orchestration Runbook

**Purpose:** 100x-engineer runbook for any coding agent picking up a task in this repo. Tells you exactly what to do, what NOT to do, what evidence to save, and when to escalate.
**Last Updated:** 2026-07-04
**Owner:** AntiVibe solo-founder + agent wiring

## Who reads this

Any agent (Claude, GPT-4, Llama, Cursor, OpenCode subagents, Sisyphus orchestrate, batch `deep`/`quick`/`writing` agents) that picks up a work task from `.omo/plans/antivibe-saas.md` or a feature follow-up.

## Workflow Ritual (10 numbered — follow EXACTLY)

1. **Locate your task** in `.omo/plans/antivibe-saas.md`. Find the `- [ ] N.` line. Do not skip reading the full task block (What to do, Must NOT do, References, Acceptance Criteria, QA Scenarios, Commit, Files).

2. **Read `docs/architecture.md` once** — cache in your context. Read `docs/system-design.md#<relevant-section>` if your task touches LLM/JWT/sandbox lifecycle/report schema. Do NOT improvise beyond these docs.

3. **Read the References listed in your task block.** Nothing outside the references. No ad-hoc grepping that wasn't delegated. Do not research beyond.

4. **Write RED test first** (TDD): failing test asserting final behavior. Commit msg ends `+red`. Example pattern:
   ```python
   # tests/scanner/test_secret_detector.py
   def test_detects_aws_key():
       findings = secret_detector.scan_string("AKIAIOSFODNN7EXAMPLE")
       assert len(findings) == 1
       assert findings[0].severity == "critical"
   ```
   Run test → confirm RED. Then commit:
   ```
   test(scanner): red — AWS key detected [+red]
   ```

5. **Write GREEN code** (minimal impl that passes RED). No premature abstraction. Commit msg ends `+green`.
   ```
   feat(scanner): AWS key matcher — green [+green]
   ```

6. **REFACTOR pass** (only after GREEN). Same tests still green. Commit msg ends `+refactor`. Skip if no obvious refactor (don't invent).

7. **Run QA Scenarios** listed in your task block. Save artifacts to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`:
   - Text outputs → `.txt`
   - JSON outputs → `.json`
   - Screenshots → `.png` (Playwright)
   - Terminal captures → `.tmux.png`
   - Curl responses → `.curl.http`

8. **Stage ONLY files listed in your task's "Files" section.** Run pre-commit commands listed. If pre-commit fails, fix the offending file; do NOT bypass.

9. **Commit with the EXACT message** from your task's `**Commit**:` block. Use Conventional Commits (`type(scope): summary`). Push branch (named `feat/<scope>-<short>` per AGENTS.md GIT COMMIT STANDARDS).

10. **Mark task complete** in plan: change `- [ ] N.` to `- [x] N.` (or orchestrator auto-marks). Update `## Status` section of every doc whose row matches this task's module (architecture.md / system-design.md / per-feature doc).

## Anti-Slop Checklist (per Metis + AGENTS.md)

Before final commit, audit your diff:
- [ ] No `as any` (TS) / no type-hint suppressions
- [ ] No `@ts-ignore` / `@ts-expect-error`
- [ ] No `print` in prod code (use `structlog` or `// eslint-disable-line` w/ justification)
- [ ] No `console.log` left in dashboard code
- [ ] No excessive comments (1 per non-obvious block, not per line). Comment style: "Validates email format. Returns false if missing @ or domain." Not: "This elegant function gracefully handles..."
- [ ] No generic names: `data`, `result`, `item`, `temp`, `payload`
- [ ] No dead code; no commented-out code blocks
- [ ] No unused imports (CI ruff + eslint catches but pre-commit fixes)
- [ ] No AI-fluff prose in docs (architecture.md is engineering, not a whitepaper)
- [ ] No marketing language ("powerful", "revolutionary", "cutting-edge")
- [ ] No emojis in any committed file
- [ ] No fake mock-LLM stubs left in tests (use `respx` / `anthropic_stub` w/ explicit reason)

## Multi-File Discipline

- **Only touch files in your task's `**Files**` section.** If a file isn't listed, don't modify it.
- If you need another file's shape → READ it; do NOT change it.
- If you discover another file needs a fix → file a follow-up task (create `.omo/drafts/followup-<topic>.md`). Do not silently modify — contaminates Wave parallelism.

## Evidence Path Convention

Every QA scenario saves evidence to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`.

Examples:
- `.omo/evidence/task-9-no-postinstall.txt` (task 9, scenario "Postinstall never runs during clone")
- `.omo/evidence/task-12-secrets-planted.txt` (task 12, scenario "Detects planted AWS + Stripe + GitHub PAT")
- `.omo/evidence/task-50-vuln-prompt-injection.txt` (task 50, prompt-injection test result)

If you skip this step → task is incomplete. F1 + F4 verification agents will reject your work.

## When Stuck

Decision tree:
1. **3 attempts failed** → re-read `docs/architecture.md` + `docs/system-design.md#<relevant-section>` + this runbook
2. **5 attempts failed** → escalate to `oracle` agent w/ explicit problem statement:
   - "Task N: <title>. Tried: <list>. Error: <exact error text>. Question: <specific question>."
3. **Oracle cannot resolve** → pause task, mark `status=blocked` in plan, escalate to user via `/omo/drafts/blocked-<task-N>.md` + create followup task in draft dir.

DO NOT "just try things" past step 5. Each attempt must be a directed hypothesis.

## Forbidden Actions (matches plan "Must NOT Have" + AGENTS.md rules)

- **No adding stacks beyond 6 whitelist** (Next.js, Express, Firebase/Firestore, FastAPI, Flask, SvelteKit)
- **No adding auth-stack forge beyond 5 whitelist** (NextAuth, Clerk, Firebase Auth, Supabase Auth, custom HS256/RS256)
- **No adding DB mocks beyond 2** (Postgres, Firestore)
- **No auto-merge of PRs** — human review mandatory (NEVER call `PUT /pulls/{n}/merge`)
- **No real outbound network from sandbox** — egress DENY ALL except localhost
- **No committing secrets / `.env.local`**
- **No skipping TDD-RED step** (infrastructure-touching tasks can use integration tests but logic MUST have unit tests RED-first)
- **No adding modules deferred to "post-MVP"** (per "Must NOT Have" in plan)
- **No `git push --force` / `git reset --hard` on main/master**
- **No `rm -rf` on directories containing `.git`**
- **No `DROP DATABASE` on prod**
- **No `docker system prune`** without user confirmation
- **No commit/push/PR without explicit user approval**

## Skill loading order (when handed a task)

Per agent-discipline (Sisyphus), check `skill` tool available skills before delegation:
- Visual work → `visual-engineering` category + `frontend-ui-ux` skill
- Git work → `git-workflow` skill + git-specialist agent
- TDD work → `tdd-workflow` skill
- Code quality → `coding-standards` skill
- Debugging → `debugging` skill
- Security review → `security-review` skill (user-stalled if scope includes new auth surface)
- PR review → `review-work` skill
- Compression before background-launch → `compress` skill (`/strategic-compact`)

## Tests Strategy (per task)

- **Business logic** (analyzers, orchestrator, normalizer, billing, auto-PR logic) → FULL TDD RED-GREEN-REFACTOR
- **Infrastructure** (Fly Machines client, Supabase calls, Docker build) → INTERGATION BEST-EFFORT integration tests w/ mocks + MANDATORY QA scenarios
- **E2E user journeys** → Playwright tests (Wave 7)

Every agent that picks up an infra task must verify via a real-equivalent mock (e.g. `respx` for httpx, `anthropic_stub` for Anthropic) and use a real QA scenario for sanity check (e.g. actually deploy a sandboxed scan on a test repo).

---

## Status

| Ritual step | Tools | Done? | Notes |
|-------------|-------|-------|-------|
| Plan located | `.omo/plans/antivibe-saas.md` | yes (partial: 14/50 tasks) | Continued generation pending |
| Architecture read | `docs/architecture.md` | yes | Shipped this sprint |
| System-design read | `docs/system-design.md` | yes | Shipped this sprint |
| TDD ring | vitest + pytest | pending | Wired in Task 8 |
| Anti-slop lint | eslint + ruff + prettier | pending | Wired in Task 8 |
| Evidence dir | `.omo/evidence/` | pending | Created on first task run |
| Feature docs template | `docs/features/*.md` | pending | Created on first feature task |