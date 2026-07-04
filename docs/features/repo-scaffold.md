# Feature: Repo Scaffold

**Purpose:** Next.js 14 App Router monorepo w/ pnpm workspace, Tailwind, shadcn/ui baseline for AntiVibe dashboard + sandbox-svc + shared-types.
**Wave:** 1  **Owner task:** 1  **Status:** pending

## Public API
- Monorepo structure (no runtime API):
  ```
  apps/dashboard/        # Next.js 14 (App Router)
  apps/api/              # FastAPI SaaS API gateway (later)
  services/sandbox-svc/  # Python sandbox orchestration
  packages/shared-types/ # TS types package
  ```
- Root `package.json` w/ `pnpm-workspace.yaml`
- `tsconfig.base.json` w/ path maps: `@antivibe/shared-types`

## Internal flow
1. Init pnpm workspace (`pnpm init` + `pnpm-workspace.yaml`)
2. Create `apps/dashboard` via `pnpm create next-app@14 dashboard --ts --tailwind --app --eslint`
3. `pnpm dlx shadcn@latest init` (copies Radix-styled components into repo; NOT npm install)
4. Add `apps/api` skeleton + FastAPI route scaffolding
5. Add `services/sandbox-svc/` w/ Python `pyproject.toml` + venv
6. Root `.env.example` w/ placeholders for FLY_API_TOKEN, SUPABASE_URL, ANTHROPIC_API_KEY, etc.
7. Config: prettier, eslint flat, ruff for Python, tsconfig.base

## Inputs
- None (greenfield)

## Outputs
- Working `pnpm dev` on `:3000` showing "AntiVibe" placeholder
- Build artifacts in `.next/`
- Fresh repo in `/home/hairzee/prods/AntiVibe`

## Acceptance criteria
- [ ] `pnpm install` + `pnpm -r build` exits 0
- [ ] `cd apps/dashboard && pnpm dev` → curl `http://localhost:3000` returns 200 w/ body containing "AntiVibe"
- [ ] `pnpm exec playwright --version` prints version (configured)
- [ ] `.env.example` exists in `apps/dashboard/` + `services/sandbox-svc/`

## Test plan
```
Scenario: Dashboard dev server boots
  Tool: Bash
  Steps: cd apps/dashboard && pnpm dev &; sleep 4; curl -sI http://localhost:3000
  Expected: HTTP 200; "AntiVibe" in body
  Evidence: .omo/evidence/task-1-dashboard-boots.txt

Scenario: Non-existent env file fails loudly
  Steps: cd apps/dashboard && rm -f .env.local && pnpm build
  Expected: Build warns NEXT_PUBLIC_SUPABASE_URL unset; still succeeds (placeholders OK)
  Evidence: .omo/evidence/task-1-env-build-error.txt
```

## Cross-references
- [see architecture.md#tech-stack-summary]
- [see ops-runbook.md#daily-deploys]
- [see system-design.md#supabase-schema-conventions]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |