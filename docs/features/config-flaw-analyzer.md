# Feature: Config Flaw Analyzer

**Purpose:** Per-stack config-flaw detector — open Firestore rules, permissive IAM, CORS *, no-op auth middleware — paired with remediation patches.
**Wave:** 2  **Owner task:** 13  **Status:** pending

## Public API
```python
@dataclass
class ConfigFinding:
    file_path: str; line: int
    severity: Severity
    title: str
    description: str
    evidence: str  # code snippet
    patch_md: str  # markdown remediation snippet
    patch_diff: str  # unified diff

class ConfigFlawAnalyzer:
    def analyze(self, repo_root: Path, *, stack: Stack, route_map: list[RouteShape]) -> list[ConfigFinding]: ...
```

## Internal flow
1. Firestore/Firebase: parse `firestore.rules` AST; flag `allow read, write: if true;` Critical; `allow read: if request.auth != null;` High (cross-ref route_map). Emit remediation patch.
2. CORS: scan `next.config.js` headers array for `Access-Control-Allow-Origin: *` + Authorization enabled → Critical
3. AWS IAM: parse `.policies/*.json` for `s3:*` + `Resource: "*"` → Critical
4. Permissive auth: detect no-op middleware (`app.use((req,res,next) => next())`) OR Next.js middleware `return NextResponse.next()` w/o auth check → Critical
5. Helmet absence in Express w/ auth → Medium

## Inputs
- repo_root + stack
- route_map from AstParser (Task 11) for cross-ref

## Outputs
- list[ConfigFinding] each with `patch_md` + `patch_diff`

## Acceptance criteria
- [ ] 6-stack happy paths pass
- [ ] Each Critical finding has `patch_md` + `patch_diff`
- [ ] Open-firestore-rules fixture → exactly 1 Critical on `firestore.rules:1` w/ remediation body

## Test plan
```
Scenario: Detects open Firestore rule + outputs remediation
  Steps: python -m scanner.config_flaws ./fixtures/vuln/firebase-open-rules --stack firebase
  Expected: 1 Critical w/ patch_md mentioning `allow read: if request.auth != null`
Scenario: Permissive Next.js CORS + auth
  Steps: scan fixture nextjs-cors-wildcard w/ Authorization route
  Expected: 1 Critical on next.config.js:5
```

## Cross-references
- [see architecture.md#tier-pipeline-diagram]
- [see security-threat-model.md#elevation-of-privilege]
- [see system-design.md#report-schema]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |