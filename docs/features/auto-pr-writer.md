# Feature: Auto-PR Writer

**Purpose:** Open GitHub PR with remediation patch — fix branch + commit + open PR + explanation body. NEVER auto-merge.
**Wave:** 5  **Owner task:** 33  **Status:** pending

## Public API
```python
class AutoPRWriter:
    async def open_fix_pr(self, *, finding: Finding, authenticated_user_id: str) -> str:
        """Returns PR URL. Raises PRCreationError on fail."""
    async def close_bad_pr(self, *, pr_number: int, reason: str) -> None: ...
```

## Internal flow
1. Branch: `antivibe/fix-<scan_id>-<finding_id>`
2. Commit: `fix(security): <finding.title>` + Co-author: `AntiVibe Bot <bot@antivibe.app>`
3. PR title: `[AntiVibe] Auto-fix: <finding.title>`
4. Body: report excerpt + evidence_curl + diff + note "This is an automated remediation suggestion. Please review carefully before merging."
5. **NEVER call PUT /pulls/{n}/merge**
6. Validate via git status push succeeds

## Acceptance criteria
- [ ] PR opened with clean diff on test vuln repo
- [ ] PR NOT merged (mergeable_state = "requires review")
- [ ] Human can merge

## Test plan
```
Scenario: PR open succeeds
  Steps: open PR with finding; verify GitHub URL exists
Scenario: Auto-merge NEVER called
  Steps: open PR → `curl -X PUT /repos/{owner}/{repo}/pulls/{n}/merge` → 404 (not implemented)
```

## Cross-references
- [see system-design.md#auto-pr-writer-flow]
- [see security-threat-model.md#elevation-of-privilege]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |