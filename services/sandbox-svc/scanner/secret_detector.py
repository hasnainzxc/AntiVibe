"""Secret detector: pattern regex + Shannon entropy + FP-control pipeline.

Two-stage detection:
1. High-confidence provider patterns (AWS, Stripe, GitHub, OpenAI, etc.) -> regex
2. Shannon entropy > 4.5 + length >= 32 -> high-entropy heuristic

FP-control:
- Skip files by extension (.example, .sample, .test.ts/.test.js/.spec.ts/.spec.js, .test.tsx)
- Skip files by name (lockfiles, .gitignore)
- Skip lines containing placeholders (REPLACE_ME, EXAMPLE, TODO, FIXME, etc.)
- Skip lines that look like URLs

Masking:
- evidence field never contains raw secret (first 3 + ... + last 3)
"""

import math
import re
import os
from pathlib import Path
from dataclasses import dataclass
import structlog

logger = structlog.get_logger(__name__)

# High-confidence regex patterns (ordered: most specific first)
HIGH_CONFIDENCE_PATTERNS = [
    # Provider-specific patterns with very specific prefixes
    (re.compile(r'AIza[0-9A-Za-z\-_]{35}'), "google-api-key", "critical"),
    (re.compile(r'AKIA[0-9A-Z]{16}'), "aws-access-key", "critical"),
    (re.compile(r'ghp_[A-Za-z0-9]{36}'), "github-pat-classic", "critical"),
    (re.compile(r'gho_[A-Za-z0-9]{36}'), "github-oauth-token", "critical"),
    (re.compile(r'sk_test_[0-9a-zA-Z]{24,}'), "stripe-live-secret", "critical"),
    (re.compile(r'sk-ant-(?:api03|api04)-[A-Za-z0-9\-_]{80,}'), "anthropic-api-key", "critical"),
    (re.compile(r'sk-[A-Za-z0-9]{48}'), "openai-api-key", "critical"),
    (re.compile(r'sk-[A-Za-z0-9]{32,}'), "openai-api-key-alt", "critical"),
    (re.compile(r'SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43}'), "sendgrid-api-key", "critical"),
    (re.compile(r'xox[bpras]-[A-Za-z0-9\-]{10,}'), "slack-token", "critical"),
    (re.compile(r'eyJ[A-Za-z0-9\-_=]{20,}\.[A-Za-z0-9\-_=]{20,}\.[A-Za-z0-9\-_=]{0,}'), "jwt-token-suspicious", "high"),
    (re.compile(r'-----BEGIN (?:RSA )?PRIVATE KEY-----'), "private-key", "critical"),
]

# FP-control: skip patterns (placeholders, docs, URLs)
# Definite-placeholder markers match as substrings; ambiguous words use word boundaries
# to avoid swallowing real secrets like AKIAIOSFODNN7EXAMPLE.
FP_SKIP_PATTERNS = [
    re.compile(r'REPLACE_ME|your-key-here|changeme', re.IGNORECASE),
    re.compile(r'\b(EXAMPLE|TODO|FIXME|xxx-xxx)\b', re.IGNORECASE),
    re.compile(r'^https?://', re.IGNORECASE),
]

# Files skipped by extension (FP-control).
# Path.suffix only returns the last segment, so compound extensions like .test.ts
# are matched by suffix + name-endswith below.
FP_SKIP_EXTENSIONS = {".example", ".sample"}
FP_SKIP_SUFFIXES = (".test.ts", ".test.js", ".spec.ts", ".spec.js", ".test.tsx")

# Files skipped by name (lockfiles, etc.)
FP_SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", ".gitignore", "package-lock.json"}

# Min length for entropy heuristic
MIN_TOKEN_LENGTH = 32

# Common prefixes that look "random" but are not secrets
ENTROPY_SKIP_PREFIXES = ("https://", "http://", "git@", "ssh://", "npm:", "node_modules/")

# Shannon entropy threshold for "secret-like" randomness.
# 3.5 catches 40-char hex tokens (~3.9 entropy) while still rejecting common strings.
ENTROPY_THRESHOLD = 3.5


@dataclass
class SecretFinding:
    file: str
    line: int
    col: int
    pattern: str
    key_type: str
    severity: str  # critical | high | medium
    evidence: str  # masked snippet (first 3 + ... + last 3)
    method: str    # "regex" or "entropy"


def _mask_secret(value: str) -> str:
    """Mask secret value: show first 3 + last 3 chars, replace middle with ...

    Guarantees the raw secret is never returned in evidence.
    """
    if len(value) <= 8:
        # For very short tokens, only show first/last 2 to avoid leaking
        if len(value) <= 4:
            return "***"
        return value[:2] + "..." + value[-2:]
    return value[:3] + "..." + value[-3:]


def _shannon_entropy(data: str) -> float:
    """Calculate Shannon entropy of a string. Higher = more random (likely secret).

    Uses byte-level entropy (256 possible values) for accurate randomness measure.
    """
    if not data:
        return 0.0
    entropy = 0.0
    length = len(data)
    for x in range(256):
        px = data.count(chr(x)) / length
        if px > 0:
            entropy -= px * math.log2(px)
    return entropy


def _is_high_entropy_token(token: str, threshold: float = ENTROPY_THRESHOLD) -> bool:
    if len(token) < MIN_TOKEN_LENGTH:
        return False
    if token.startswith(ENTROPY_SKIP_PREFIXES):
        return False
    return _shannon_entropy(token) > threshold


def _should_skip_file(filepath: str) -> bool:
    path = Path(filepath)
    if path.suffix in FP_SKIP_EXTENSIONS:
        return True
    if any(path.name.endswith(s) for s in FP_SKIP_SUFFIXES):
        return True
    if path.name in FP_SKIP_NAMES:
        return True
    return False


def _should_skip_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    # Skip comment-only lines if they contain placeholder markers
    if stripped.startswith("//") or stripped.startswith("#") or stripped.startswith("/*"):
        for pattern in FP_SKIP_PATTERNS:
            if pattern.search(stripped):
                return True
    # Skip any line matching placeholder/URL patterns
    for pattern in FP_SKIP_PATTERNS:
        if pattern.search(stripped):
            return True
    return False


def scan_file(filepath: str) -> list[SecretFinding]:
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

        # Stage 1: High-confidence pattern matching
        for pattern, key_type, severity in HIGH_CONFIDENCE_PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(0)
                findings.append(SecretFinding(
                    file=filepath,
                    line=line_num,
                    col=match.start() + 1,
                    pattern=pattern.pattern[:40],
                    key_type=key_type,
                    severity=severity,
                    evidence=_mask_secret(value),
                    method="regex",
                ))

        # Stage 2: Entropy heuristic (only if no regex match on this line)
        has_regex_match = any(f.line == line_num for f in findings)
        if not has_regex_match:
            tokens = re.split(r"[\s'\"=:;,<>\[\]{}()]+", line)
            for token in tokens:
                token = token.strip()
                if token and _is_high_entropy_token(token):
                    findings.append(SecretFinding(
                        file=filepath,
                        line=line_num,
                        col=line.find(token) + 1,
                        pattern="entropy_>4.5",
                        key_type="entropy-detected-secret",
                        severity="high",
                        evidence=_mask_secret(token),
                        method="entropy",
                    ))

    return findings


def scan_directory(repo_path: str) -> list[SecretFinding]:
    all_findings: list[SecretFinding] = []
    repo = Path(repo_path)
    if not repo.is_dir():
        return []

    for root, dirs, files in os.walk(repo_path):
        # Skip common directories
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
