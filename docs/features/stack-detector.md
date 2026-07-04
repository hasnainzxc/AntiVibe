# Feature: Stack Detector

**Purpose:** Heuristic detection of which whitelisted stack (Next.js/Express/Firebase/FastAPI/Flask/SvelteKit) the cloned repo is.
**Wave:** 2  **Owner task:** 10  **Status:** pending

## Public API
```python
def detect_stack(repo_root: Path) -> Stack:
    """Returns Stack enum. Raises UnsupportedStackError on non-match."""

class UnsupportedStackError(Exception): ...
```

## Internal flow
1. Read `package.json` or `pyproject.toml` / `requirements.txt` at repo root
2. Apply ordered rules (declarative, per-stack sub-rule):
   - nextjs: `next` dep in package.json → strong; + `app/` or `pages/` dir → decisive
   - express: `express` dep → strong; + `routes/` and no Next → decisive
   - firebase: `firebase.json` OR `.firebaserc` → decisive
   - fastapi: `fastapi` in requirements.txt OR pyproject.toml → decisive
   - flask: `flask` in requirements.txt → decisive
   - sveltekit: `svelte.config.js` + `@sveltejs/kit` dep → decisive
3. On polyglot tie → return FIRST top-of-whitelist match + log `stack.tie`
4. On no match → raise `UnsupportedStackError`

## Inputs
- repo_root: Path

## Outputs
- Stack enum value
- Structlog `stack.detected` OR `stack.unsupported` OR `stack.tie`

## Acceptance criteria
- [ ] `pytest tests/scanner/test_detect_stack.py` passes 6 happy + 1 rejection tests
- [ ] When run over 50 mixed fixture repos (Task 47): accuracy > 90% on the 6 whitelisted stacks

## Test plan
```
Scenario: Detects Next.js
  Steps: python -m scanner.detect_stack ./fixtures/stacks/next-app
  Expected: prints `nextjs`
Scenario: Rejects rails (unsupported)
  Steps: python -m scanner.detect_stack ./fixtures/stacks/racist
  Expected: exit 1 + `UnsupportedStackError` stderr
```

## Cross-references
- [see architecture.md#whitelists-locked]
- [see agent-orchestration.md#forbidden-actions]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |