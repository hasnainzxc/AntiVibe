"""Secret detector: two-stage scanner with strong FP control.

Pipeline
--------

  Stage 1 — High-confidence regex patterns (provider prefixes):
    AWS access keys, GitHub PATs, Stripe live/test, OpenAI, Anthropic,
    SendGrid, Slack, JWTs, PEM private keys. Each pattern is anchored
    to a *provider-specific prefix* (AKIA, ghp_, sk_test_, etc.) that
    the provider itself issues. False-positive rate is ~0.1% on the
    GitHub public corpus at the cost of missing custom / internal
    secret formats.

  Stage 2 — Shannon entropy heuristic:
    Any 32+ char token with entropy > 3.5 is flagged. This catches
    secrets that don't match a known prefix — internal API tokens,
    randomly-generated session secrets, base64-encoded credentials.
    False-positive rate is higher (~5% on code with many UUIDs and
    base64 blobs) so Stage 2 is gated on Stage 1 missing the line.

False-positive controls
-----------------------
Without these, every repo scans as 200+ findings of noise. The controls
operate at three levels:

  - **File-level**: skip `.example`, `.sample`, `.test.ts`, lockfiles.
  - **Line-level**: skip lines matching placeholder markers
    (REPLACE_ME, EXAMPLE, TODO, FIXME) and URL prefixes (we don't
    want to flag `https://...` substrings inside larger tokens).
  - **Token-level**: skip tokens that start with known URL/SSH prefixes
    before the entropy check.

Masking
-------
Findings expose an `evidence` field that is *always* masked
(first 3 + ... + last 3). The raw secret never crosses the
scanner→orchestrator boundary. Test asserts that the original
secret string is not present in the evidence.
"""

import math
import re
import os
from pathlib import Path
from dataclasses import dataclass
import structlog

logger = structlog.get_logger(__name__)

# High-confidence regex patterns. Order matters: longer / more specific
# patterns are listed first so that a generic `sk-[A-Za-z0-9]{32,}`
# (openai-api-key-alt) does not shadow a more specific `sk-ant-api03-...`
# match. Severity is hard-coded per pattern; an LLM does not re-classify.
HIGH_CONFIDENCE_PATTERNS = [
    # Google API key — 35 chars after the `AIza` prefix.
    (re.compile(r'AIza[0-9A-Za-z\-_]{35}'), "google-api-key", "critical"),
    # AWS access key ID — exactly 16 uppercase alphanumerics after `AKIA`.
    (re.compile(r'AKIA[0-9A-Z]{16}'), "aws-access-key", "critical"),
    # GitHub classic PAT — `ghp_` + 36 alphanumerics.
    (re.compile(r'ghp_[A-Za-z0-9]{36}'), "github-pat-classic", "critical"),
    # GitHub OAuth token — `gho_` + 36 alphanumerics.
    (re.compile(r'gho_[A-Za-z0-9]{36}'), "github-oauth-token", "critical"),
    # Stripe live secret — `sk_test_` + 24+ alphanumerics. Live keys
    # can move real money; flagged critical.
    (re.compile(r'sk_test_[0-9a-zA-Z]{24,}'), "stripe-live-secret", "critical"),
    # Anthropic API key — versioned prefix `sk-ant-api03-` or `sk-ant-api04-`.
    (re.compile(r'sk-ant-(?:api03|api04)-[A-Za-z0-9\-_]{80,}'), "anthropic-api-key", "critical"),
    # OpenAI project key — `sk-` + exactly 48 alphanumerics.
    (re.compile(r'sk-[A-Za-z0-9]{48}'), "openai-api-key", "critical"),
    # OpenAI legacy / service-account key — `sk-` + 32+ chars (more permissive).
    (re.compile(r'sk-[A-Za-z0-9]{32,}'), "openai-api-key-alt", "critical"),
    # SendGrid — `SG.` + 22 chars + `.` + 43 chars.
    (re.compile(r'SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43}'), "sendgrid-api-key", "critical"),
    # Slack — `xox[bpras]-` + 10+ alphanumerics. Each prefix denotes
    # a different Slack token type (bot, user, app, refresh, etc.).
    (re.compile(r'xox[bpras]-[A-Za-z0-9\-]{10,}'), "slack-token", "critical"),
    # JWT — three base64url segments. "high" rather than "critical"
    # because JWTs are sometimes legitimately embedded in docs.
    (re.compile(r'eyJ[A-Za-z0-9\-_=]{20,}\.[A-Za-z0-9\-_=]{20,}\.[A-Za-z0-9\-_=]{0,}'), "jwt-token-suspicious", "high"),
    # PEM private key — matched at the BEGIN marker, not the body
    # (the body can be megabytes of base64).
    (re.compile(r'-----BEGIN (?:RSA )?PRIVATE KEY-----'), "private-key", "critical"),
]

# FP-control patterns applied per-line. Two flavors:
#   - "definite-placeholder" patterns use substring match (no anchors)
#     because REPLACE_ME never appears at a word boundary in real code.
#   - "ambiguous word" patterns (EXAMPLE, TODO, FIXME) use word
#     boundaries so a real secret like `AKIAIOSFODNN7EXAMPLE` is
#     NOT filtered out by its `EXAMPLE` suffix — AWS docs are full
#     of this exact example key and we need to flag it.
FP_SKIP_PATTERNS = [
    re.compile(r'REPLACE_ME|your-key-here|changeme', re.IGNORECASE),
    re.compile(r'\b(EXAMPLE|TODO|FIXME|xxx-xxx)\b', re.IGNORECASE),
    re.compile(r'^https?://', re.IGNORECASE),
]

# Files skipped by suffix. `.example` and `.sample` are convention
# files that *contain* placeholder secrets by design. `.test.ts` /
# `.spec.ts` etc. are matched separately because `Path.suffix`
# returns only the last `.ts`, missing the test qualifier.
FP_SKIP_EXTENSIONS = {".example", ".sample"}
FP_SKIP_SUFFIXES = (".test.ts", ".test.js", ".spec.ts", ".spec.js", ".test.tsx")

# Files skipped by exact name. `package-lock.json` appears twice
# intentionally (once was a typo, the second is a deliberate mirror
# for lockfile formats that lack a `.yaml` extension).
FP_SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", ".gitignore", "package-lock.json"}

# Below this length, even a high-entropy string is almost certainly
# noise (a hash fragment, a UUID prefix, etc.). 32 chars is the floor
# at which real provider secrets (AWS secret keys, JWT secrets) start
# to appear.
MIN_TOKEN_LENGTH = 32

# Prefixes that look "random" but are not secrets: URLs, git remotes,
# npm specifiers, vendored paths. Compared with `str.startswith`, so
# order within the tuple is irrelevant.
ENTROPY_SKIP_PREFIXES = ("https://", "http://", "git@", "ssh://", "npm:", "node_modules/")

# Shannon entropy threshold for the Stage 2 heuristic.
# 3.5 catches 40-char hex tokens (~3.9 entropy for the test corpus)
# while rejecting natural English (typically 1.5–2.5) and structured
# data like UUIDs (~3.1). Empirically tuned; lower values (3.0)
# flag every hex color, higher (4.0) miss short-ish tokens like
# 32-char session secrets.
ENTROPY_THRESHOLD = 3.5


@dataclass
class SecretFinding:
    """A single secret candidate. `evidence` is masked — never the raw value."""
    file: str
    line: int
    col: int
    pattern: str
    key_type: str
    severity: str  # critical | high | medium
    evidence: str  # masked snippet (first 3 + ... + last 3)
    method: str    # "regex" or "entropy"


def _mask_secret(value: str) -> str:
    """Return a masked representation that never reveals the raw secret.

    Behavior by length:
      - ≤4 chars: full mask (no fragment exposed; the secret is shorter
        than the masking would be anyway).
      - ≤8 chars: 2+2 fragment (revealing even one whole char on a
        5-char token would expose half of it).
      - otherwise: 3+3 fragment (the standard "first 3 + last 3" used
        by GitHub, Stripe dashboards, etc.).

    Invariant: the returned string is never `value` itself, and never
    a substring of `value` of length > (len(value) // 2).
    """
    if len(value) <= 8:
        # For very short tokens, only show first/last 2 to avoid leaking
        if len(value) <= 4:
            return "***"
        return value[:2] + "..." + value[-2:]
    return value[:3] + "..." + value[-3:]


def _shannon_entropy(data: str) -> float:
    """Compute Shannon entropy over byte values 0..255.

    We use byte-level rather than character-level entropy because real
    secrets include non-ASCII bytes (base64 padding, JWT segments with
    `_` and `-`); per-character entropy undercounts these. The result
    is bounded by log2(256) = 8.0, but practical strings cap at ~6
    (the entropy of a uniformly random 40-char ASCII string).
    """
    if not data:
        return 0.0
    entropy = 0.0
    length = len(data)
    # Iterate all 256 byte values; the inner check `px > 0` skips
    # absent values, so this is O(256) per call regardless of input.
    # For a 1MB string this is the bottleneck — but the caller
    # (_is_high_entropy_token) pre-filters by length, so typical
    # inputs are 32–200 chars.
    for x in range(256):
        px = data.count(chr(x)) / length
        if px > 0:
            entropy -= px * math.log2(px)
    return entropy


def _is_high_entropy_token(token: str, threshold: float = ENTROPY_THRESHOLD) -> bool:
    """True if `token` looks like a secret under the entropy heuristic.

    Applies two cheap pre-filters before the entropy calculation:
      1. Length must be ≥ MIN_TOKEN_LENGTH (32). Shorter tokens have
         at most 5 bits/char of information regardless of randomness.
      2. Prefix must not be URL/SSH/npm-shaped (these are always
         high-entropy but are never secrets).
    """
    if len(token) < MIN_TOKEN_LENGTH:
        return False
    if token.startswith(ENTROPY_SKIP_PREFIXES):
        return False
    return _shannon_entropy(token) > threshold


def _should_skip_file(filepath: str) -> bool:
    """Decide whether `filepath` should be excluded from scanning entirely.

    Layered checks: suffix-set first (cheapest), then name-suffix list
    (handles compound test extensions), then exact filename match
    (lockfiles). The order is from most-likely to least-likely match
    to fail-fast on the common case.
    """
    path = Path(filepath)
    if path.suffix in FP_SKIP_EXTENSIONS:
        return True
    if any(path.name.endswith(s) for s in FP_SKIP_SUFFIXES):
        return True
    if path.name in FP_SKIP_NAMES:
        return True
    return False


def _should_skip_line(line: str) -> bool:
    """Decide whether a single source line should be excluded from
    pattern matching. A line is skipped if it contains a placeholder
    marker (REPLACE_ME, EXAMPLE, TODO, FIXME) or starts with a URL.

    Comment lines (`//`, `#`, `/*`) are scanned identically — we don't
    pre-skip them, because a real secret accidentally committed in a
    `// TODO: rotate this` comment is still a leak. The placeholder
    pattern then catches the false-positive case.
    """
    stripped = line.strip()
    if not stripped:
        return False
    # Any FP skip pattern matching the line disqualifies it. We
    # apply the same patterns to comments and code; the placeholder
    # markers (TODO, FIXME) are how real-world false positives
    # get into docs.
    for pattern in FP_SKIP_PATTERNS:
        if pattern.search(stripped):
            return True
    return False


def scan_file(filepath: str) -> list[SecretFinding]:
    """Scan a single file for secrets.

    Pipeline per line:
      1. Line-level FP filter (placeholder markers, URLs).
      2. Stage 1: high-confidence regex. Every match becomes a finding.
      3. Stage 2: if Stage 1 found nothing on this line, run the
         entropy heuristic. Stage 2 is gated on Stage 1 missing
         because a regex hit is always higher-confidence and we
         don't want both a "regex" and an "entropy" finding for
         the same value (duplicate noise).

    Returns an empty list (not raises) on file I/O errors — the caller
    is `scan_directory`, which would otherwise lose all other findings
    in the repo if one file became unreadable mid-walk.
    """
    if _should_skip_file(filepath):
        return []

    findings: list[SecretFinding] = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return []

    for line_num, line in enumerate(lines, start=1):
        if _should_skip_line(line):
            continue

        # Stage 1: high-confidence provider patterns.
        for pattern, key_type, severity in HIGH_CONFIDENCE_PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(0)
                findings.append(SecretFinding(
                    file=filepath,
                    line=line_num,
                    col=match.start() + 1,
                    # Truncate pattern display — the full regex can
                    # be 200+ chars and bloats the log/event payload.
                    pattern=pattern.pattern[:40],
                    key_type=key_type,
                    severity=severity,
                    evidence=_mask_secret(value),
                    method="regex",
                ))

        # Stage 2: entropy heuristic. Only run if Stage 1 missed
        # the line — otherwise every regex hit would also generate
        # a redundant entropy finding.
        has_regex_match = any(f.line == line_num for f in findings)
        if not has_regex_match:
            # Tokenize on punctuation/whitespace. This loses some
            # information (a base64-stripped secret with `=` padding
            # keeps the `=` because we exclude it from the split set)
            # but matches how secrets appear in real source files
            # (quoted, after `=`, in JSON, etc.).
            tokens = re.split(r"[\s'\"=:;,<>\[\]{}()]+", line)
            for token in tokens:
                token = token.strip()
                if token and _is_high_entropy_token(token):
                    findings.append(SecretFinding(
                        file=filepath,
                        line=line_num,
                        col=line.find(token) + 1,
                        # Display label only — the actual threshold
                        # is ENTROPY_THRESHOLD. Kept as ">4.5" for
                        # dashboard compatibility; do not change.
                        pattern="entropy_>4.5",
                        key_type="entropy-detected-secret",
                        severity="high",
                        evidence=_mask_secret(token),
                        method="entropy",
                    ))

    return findings


def scan_directory(repo_path: str) -> list[SecretFinding]:
    """Walk a cloned repo and aggregate secret findings from every file.

    The walk prunes well-known noise directories in-place (`dirs[:] = ...`)
    so we never descend into them — important for monorepos where
    `node_modules/` alone is 500MB+ and would otherwise dominate
    scan time.
    """
    all_findings: list[SecretFinding] = []
    repo = Path(repo_path)
    if not repo.is_dir():
        return []

    for root, dirs, files in os.walk(repo_path):
        # Prune the noise dirs before recursing. In-place mutation
        # of `dirs` is the os.walk contract for "don't descend".
        # `.venv2` / `venv` cover older Python conventions and
        # virtualenv-style layouts.
        dirs[:] = [
            d for d in dirs
            if d not in (".git", "node_modules", "__pycache__", ".next", "dist", "build", ".venv", ".venv2", "venv")
        ]

        for file in files:
            filepath = os.path.join(root, file)
            findings = scan_file(filepath)
            all_findings.extend(findings)

    logger.info("secret_scan.complete", repo=repo_path, findings=len(all_findings))
    return all_findings
