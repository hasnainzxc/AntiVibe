# Feature: CI/Test Infrastructure

**Purpose:** Vitest + Pytest + Playwright + GitHub Actions workflow config. Blocks merging on failing lint/test/build.
**Wave:** 1  **Owner task:** 8  **Status:** pending

## Public API
- `.github/workflows/ci.yml` — runs on push + pull_request
- `.github/workflows/e2e.yml` — manual dispatch only
- `vitest.workspace.ts` + per-package `vitest.config.ts`
- `playwright.config.ts` at `apps/dashboard/`
- `pytest.ini` + `ruff.toml` at `services/sandbox-svc/`
- `eslint.config.js` at root (flat config)

## Internal flow
1. CI pipeline:
   ```
   pnpm install --frozen-lockfile
   pnpm -r lint
   pnpm -r test
   pnpm -r build
   pip install -r services/sandbox-svc/requirements.txt
   pytest services/sandbox-svc
   ```
2. Caching: `setup-node@v4` pnpm-store, `setup-python@v5` __pycache__
3. Required status check blocks merge
4. E2E workflow manual-only (avoid burning CI minutes on Playwright)

## Inputs
- Repo push or PR event (github event payload)
- Secrets: `ANTHROPIC_API_KEY` (only for E2E workflow; CI uses mocks)

## Outputs
- CI green/red status on PR
- Test reports (Junit XML) uploaded as artifacts

## Acceptance criteria
- [ ] CI green path completes < 3 min
- [ ] Lint failure blocks merge
- [ ] `pretter --check` passes
- [ ] `ruff check .` passes
- [ ] `.gitignore` covers `.next`, `__pycache__`, `.venv`, `.omo/evidence`, `.env`

## Test plan
```
Scenario: CI lights green on no-op commit
  Steps: act -W .github/workflows/ci.yml push
  Expected: green
  Evidence: .omo/evidence/task-8-act-green.txt

Scenario: Lint error fails CI
  Steps: introduce `const x: any = 1`; act -W .github/workflows/ci.yml pull_request
  Expected: red with lint failure
  Evidence: .omo/evidence/task-8-act-red.txt
```

## Cross-references
- [see agent-orchestration.md#tests-strategy-per-task]
- [see ops-runbook.md#daily-deploys]
- [see security-threat-model.md#elevation-of-privilege]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |