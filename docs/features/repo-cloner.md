# Feature: Repo Cloner

**Purpose:** Secure shallow clone of target GitHub repo into sandbox-svc FS w/ size cap + LFS block + postinstall block.
**Wave:** 2  **Owner task:** 9  **Status:** pending

## Public API
```python
# services/sandbox-svc/scanner/clone.py
async def clone_repo(repo_url: str, *, branch_or_commit: str | None = None, out_dir: Path) -> Path:
    """Shallow clone (--depth 1, no LFS, size cap 500MB). Returns path to clone root."""

class RepoTooLarge(Exception): ...
class UnsupportedUrl(Exception): ...
class MaliciousPostinstall(Exception): ...
```

## Internal flow
1. Validate URL: only `https://github.com/{owner}/{repo}(/tree/{branch})?` shape
2. `git ls-remote --heads <url>` to fetch refs; estimate tree size
3. If estimated > 500MB → raise `RepoTooLarge`
4. `GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 <url> <out_dir>` (no `--recurse-submodules`)
5. After clone: rewrite `.git/config` to disable `core.hooksPath`; rewrite `.npmrc` w/ `ignore-scripts=true`
6. Set env vars `npm_config_ignore_scripts=true` + `PIP_NO_BUILD_ISOLATION=0` for any future install calls
7. Pin in `git ls-remote` returns SHA in case clone scrapes drift

## Inputs
- repo_url: string (HTTPS only)
- branch_or_commit: optional SHA or branch name

## Outputs
- Cloned tree at `out_dir`
- Modified `.git/config`, `.npmrc` w/ security hardening

## Acceptance criteria
- [ ] `pytest tests/scanner/test_clone.py` passes 5 tests
- [ ] `.npmrc` in clone has `ignore-scripts=true`
- [ ] Tree size > 500MB rejected w/ `RepoTooLarge`
- [ ] No `git lfs` invocation in code (`git grep`)

## Test plan
```
Scenario: Shallow clone of small repo
  Steps: python -m scanner.clone https://github.com/supabase/supabase --out /tmp/c1
  Expected: tree present; no .git/lfs objects
  Evidence: .omo/evidence/task-9-small-clone.txt

Scenario: Oversized repo pre-rejected
  Steps: python -m scanner.clone file:///tmp/fake-huge --out /tmp/c2
  Expected: exit 2 + stderr {"error":"repo_too_large"}
  Evidence: .omo/evidence/task-9-size-cap.txt

Scenario: Postinstall never runs
  Steps: Fixture postinstall writes /tmp/victim.txt; clone fixture
  Expected: /tmp/victim.txt absent
  Evidence: .omo/evidence/task-9-no-postinstall.txt
```

## Cross-references
- [see sandbox-isolation.md#repo-clone-guardrails]
- [see security-threat-model.md#elevation-of-privilege]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |