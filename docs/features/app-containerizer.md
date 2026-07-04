# Feature: App Containerizer

**Purpose:** Generate per-stack Dockerfile for app-under-test + build image for sandbox Fly Machine. 6-stack whitelist support.
**Wave:** 3  **Owner task:** 16  **Status:** pending

## Public API
```python
class AppContainerizer:
    def generate_dockerfile(self, *, stack: Stack, repo_root: Path) -> str: ...
    async def build_image(self, *, stack: Stack, repo_root: Path, image_tag: str) -> str:
        """Returns Fly image registry ref."""

UNSUPPORTED_STACK = "cant containerize (stack not in whitelist)"
```

## Internal flow
1. Per-stack Dockerfile template:
   - **nextjs**: Next.js standalone build → `node server.js` on 3000
   - **express**: `tsc && node dist/index.js` on 8000 (or nodemon dev mode)
   - **firebase**: firebase emulators container w/ firestore rules + functions mounted
   - **fastapi**: `uvicorn app:app --host 0.0.0.0 --port 8000`
   - **flask**: `gunicorn app:app --bind 0.0.0.0:5000`
   - **sveltekit**: `npm run build && npm run preview -- --host 0.0.0.0 --port 4173`
2. Generate `Dockerfile.antivibe` in sandbox build scratch dir (not in user repo)
3. Build via `flyctl deploy --dockerfile Dockerfile.antivibe --no-release --image-only` OR `docker build` then push to Fly registry
4. Image name: `registry.fly.io/antivibe-sfc-<scan_id>:latest`

## Inputs
- stack enum (from task 10)
- repo_root Path

## Outputs
- Fly image registry ref (string)
- Dockerfile scratch file (lives in sandbox-svc FS, NOT user repo)

## Acceptance criteria
- [ ] All 6 stacks produce buildable Dockerfile on fixture repos
- [ ] Image build cold-cache < 90s per fixture
- [ ] App boots w/no outbound calls (egress DENY enforced post-container start by Fly)

## Test plan
```
Scenario: Next.js app containerizes
  Steps: python -m sandbox.containerize --stack nextjs ./fixtures/stacks/next-app
  Expected: image ref printed; image boot on Fly returns HTTP 200 on /
Scenario: Unsupported stack rejected
  Steps: --stack custom ./fixture
  Expected: error UNSUPPORTED_STACK
```

## Cross-references
- [see sandbox-isolation.md#machine-specs]
- [see architecture.md#tier-pipeline-diagram]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |