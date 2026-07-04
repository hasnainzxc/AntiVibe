# Feature: Secret Detector

**Purpose:** Two-stage detector (high-confidence regex + entropy heuristic) for hardcoded API keys/secrets in cloned source. FP-rate target <5% on clean fixtures.
**Wave:** 2  **Owner task:** 12  **Status:** pending

## Public API
```python
@dataclass
class SecretFinding:
    file_path: str; line: int; col: int
    pattern_name: str
    severity: Severity  # Critical for live-secret patterns, High for entropy-only
    masked_value: str  # e.g. "AKIA...7XYZ"

class SecretDetector:
    def __init__(self, *, entropy_threshold: float = 4.5): ...
    def scan_file(self, path: Path) -> list[SecretFinding]: ...
    def scan_tree(self, root: Path) -> list[SecretFinding]: ...
    def scan_string(self, content: str) -> list[SecretFinding]: ...
```

## Internal flow
1. Pattern matchers (ordered): Google API key, AWS (`AKIA...`), GitHub PAT (`ghp_`/`gho_`), Stripe (`sk_live_`), Supabase JWT service-role, Firebase admin JSON, Twilio SID+token co-occurrence, SendGrid (`SG.`), OpenAI (`sk-`), Anthropic (`sk-ant-`), Slack (`xox`), private keys (`-----BEGIN...`)
2. Entropy heuristic: Shannon entropy > 4.5 over tight tokens passing gitignore-filter
3. FP-control: drop < 32 chars; drop in docstrings; drop in `*.example`/`*.sample`/`*.test.ts`/`*_test.go`/`*spec*.ts`
4. Calibration tool: `--calibrate ./fixtures/clean` → assert 0 findings

## Inputs
- Cloned repo tree

## Outputs
- list[SecretFinding] (severity, file_path, line, col, pattern_name, masked_value)

## Acceptance criteria
- [ ] All 5 planted secrets detected; 0 false positives on clean fixture
- [ ] No raw secret value in structlog output (masked)
- [ ] Per file scan latency < 100ms

## Test plan
```
Scenario: Detects AWS + Stripe + GitHub PAT
  Steps: python -m scanner.secret_detector ./fixtures/secrets/planted
  Expected: 3 findings, all critical
Scenario: Clean repo = 0 findings
  Steps: python -m scanner.secret_detector ./fixtures/clean/nextjs-clean
  Expected: {}
Scenario: No raw secrets in stdout
  Steps: python -m scanner.secret_detector ./fixtures/secrets/planted | grep -E "(AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36})" | wc -l
  Expected: 0 (masked)
```

## Cross-references
- [see security-threat-model.md#info-disclosure]
- [see security-threat-model.md#elevation-of-privilege]
- [see agent-orchestration.md#anti-slop-checklist] (masking discipline)

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |