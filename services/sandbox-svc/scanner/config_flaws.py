"""Config-flaw analyzer: Firestore rules, IAM, CORS, permissive auth, missing security headers.

Detects misconfigurations in:
- Firestore rules (open read/write without auth check)
- CORS wildcards combined with authenticated routes
- IAM policies with broad Action+Resource wildcards
- Express no-op auth middleware
- Express apps missing helmet

Each finding carries patch_md (human-readable fix) and patch_diff (unified diff).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from enum import Enum
import structlog

logger = structlog.get_logger(__name__)


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ConfigFlawFinding:
    file: str
    line: int
    rule_id: str
    title: str
    description: str
    severity: Severity
    patch_md: str  # Markdown snippet
    patch_diff: str = ""  # Unified diff
    evidence: str = ""


# ─── Firestore rules analyzer ───

def _analyze_firestore_rules(repo: Path) -> list[ConfigFlawFinding]:
    findings = []
    rules_files = list(repo.rglob("firestore.rules"))
    if not rules_files:
        return findings

    for rules_path in rules_files:
        try:
            content = rules_path.read_text(errors="ignore")
        except OSError:
            continue
        lines = content.split("\n")

        for i, line in enumerate(lines, 1):
            # Critical: allow read/write: if true (no auth check)
            if re.search(r'allow\s+read\s*,\s*write\s*:\s*if\s+true\s*;', line):
                findings.append(ConfigFlawFinding(
                    file=str(rules_path),
                    line=i,
                    rule_id="FIRESTORE_OPEN_RW",
                    title="Open Firestore read/write (no auth check)",
                    description="`allow read, write: if true` exposes the entire collection to anyone. This is the textbook multi-tenant leak.",
                    severity=Severity.CRITICAL,
                    patch_md=(
                        "```diff\n"
                        "- allow read, write: if true;\n"
                        "+ allow read, write: if request.auth != null\n"
                        "     && request.auth.uid in resource.data.admins;\n"
                        "```\n\n"
                        "**Fix:** Add authentication check. For multi-tenant data, scope to user or admin field on the document."
                    ),
                    patch_diff=(
                        f"--- a/{rules_path}\n"
                        f"+++ b/{rules_path}\n"
                        f"@@ -1,{i} +1,2 @@\n"
                        f"-allow read, write: if true;\n"
                        f"+allow read, write: if request.auth != null\n"
                        f"+  && request.auth.uid in resource.data.admins;\n"
                    ),
                    evidence=line.strip(),
                ))

            # High: allow read: if true (only read, but still wide open)
            if re.search(r'allow\s+read\s*:\s*if\s+true\s*;', line) and "write" not in line:
                findings.append(ConfigFlawFinding(
                    file=str(rules_path),
                    line=i,
                    rule_id="FIRESTORE_OPEN_READ",
                    title="Open Firestore read (no auth check)",
                    description="`allow read: if true` exposes all documents to anyone with the project ID.",
                    severity=Severity.CRITICAL,
                    patch_md=(
                        "```diff\n"
                        "- allow read: if true;\n"
                        "+ allow read: if request.auth != null;\n"
                        "```"
                    ),
                    evidence=line.strip(),
                ))

    return findings


# ─── CORS analyzer ───

def _analyze_cors(repo: Path) -> list[ConfigFlawFinding]:
    findings = []
    cors_re = re.compile(r'Access-Control-Allow-Origin.*\*')

    for filepath in [repo / "next.config.js", repo / "next.config.mjs", repo / "next.config.ts"]:
        if not filepath.exists():
            continue
        try:
            content = filepath.read_text(errors="ignore")
        except OSError:
            continue

        for i, line in enumerate(content.split("\n"), 1):
            if cors_re.search(line):
                api_dir = repo / "app" / "api"
                auth_route_exists = False
                if api_dir.exists():
                    for route_file in api_dir.rglob("route.ts"):
                        if not route_file.is_file():
                            continue
                        try:
                            if "Authorization" in route_file.read_text(errors="ignore"):
                                auth_route_exists = True
                                break
                        except OSError:
                            continue
                if auth_route_exists:
                    findings.append(ConfigFlawFinding(
                        file=str(filepath),
                        line=i,
                        rule_id="CORS_WILDCARD_AUTH",
                        title="CORS wildcard with auth routes",
                        description="Access-Control-Allow-Origin: * combined with authenticated routes allows CSRF/exfiltration from any origin.",
                        severity=Severity.CRITICAL,
                        patch_md=(
                            "```diff\n"
                            '- "Access-Control-Allow-Origin": "*"\n'
                            '+ "Access-Control-Allow-Origin": "https://yourapp.com",\n'
                            '+ "Access-Control-Allow-Credentials": "true"\n'
                            "```\n\n"
                            "**Fix:** Use a specific allowlist. Never combine `*` with `Access-Control-Allow-Credentials`."
                        ),
                        evidence=line.strip(),
                    ))

    return findings


# ─── IAM analyzer ───

def _analyze_iam(repo: Path) -> list[ConfigFlawFinding]:
    findings = []

    for policy_path in repo.rglob("*.policies"):
        try:
            content = policy_path.read_text(errors="ignore")
        except OSError:
            continue
        if '"s3:*"' in content and re.search(r'"Resource"\s*:\s*"\*"', content):
            findings.append(ConfigFlawFinding(
                file=str(policy_path),
                line=1,
                rule_id="IAM_BROAD_S3",
                title="IAM policy grants s3:* on all resources",
                description="Wildcard Action + Resource grants unrestricted S3 access. Violates least-privilege.",
                severity=Severity.CRITICAL,
                patch_md=(
                    "```json\n"
                    "{\n"
                    '  "Action": ["s3:GetObject", "s3:PutObject"],\n'
                    '  "Resource": "arn:aws:s3:::your-bucket/*"\n'
                    "}\n"
                    "```"
                ),
                evidence="s3:* + Resource: *",
            ))

    return findings


# ─── Permissive auth analyzer ───

def _analyze_permissive_auth(repo: Path) -> list[ConfigFlawFinding]:
    findings = []

    # Express: app.use((req, res, next) => next())
    noop_pattern = re.compile(r'app\.use\s*\(\s*\(req\s*,\s*res\s*,\s*next\s*\)\s*=>\s*next\s*\(\s*\)\s*\)')
    for ext in ("js", "ts"):
        for filepath in repo.rglob(f"app.{ext}"):
            try:
                content = filepath.read_text(errors="ignore")
            except OSError:
                continue
            if noop_pattern.search(content):
                findings.append(ConfigFlawFinding(
                file=str(filepath),
                line=1,
                rule_id="EXPRESS_NOOP_AUTH",
                title="Express no-op auth middleware",
                description="`(req, res, next) => next()` allows all requests through without auth check.",
                severity=Severity.CRITICAL,
                patch_md=(
                    "```diff\n"
                    "- app.use((req, res, next) => next());\n"
                    "+ app.use(authMiddleware); // require auth before protected routes\n"
                    "```"
                ),
                evidence="no-op middleware detected",
            ))
                break

    return findings


# ─── Helmet analyzer ───

def _analyze_missing_helmet(repo: Path) -> list[ConfigFlawFinding]:
    findings = []
    pkg_path = repo / "package.json"
    if not pkg_path.exists():
        return findings

    try:
        pkg = json.loads(pkg_path.read_text())
    except (json.JSONDecodeError, OSError):
        return findings

    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    has_express = "express" in deps
    has_helmet = "helmet" in deps

    if has_express and not has_helmet:
        findings.append(ConfigFlawFinding(
            file=str(pkg_path),
            line=1,
            rule_id="NO_HELMET",
            title="Express app missing helmet",
            description="Without helmet, security headers (X-Frame-Options, X-Content-Type-Options, etc.) are not set.",
            severity=Severity.MEDIUM,
            patch_md=(
                "```bash\n"
                "pnpm add helmet\n"
                "```\n\n"
                "```diff\n"
                "  const app = express();\n"
                "+ app.use(helmet());\n"
                "```"
            ),
            evidence="no helmet in dependencies",
        ))

    return findings


# ─── Main dispatch ───

ANALYZERS = [
    _analyze_firestore_rules,
    _analyze_cors,
    _analyze_iam,
    _analyze_permissive_auth,
    _analyze_missing_helmet,
]


def analyze_config_flaws(repo_path: str, stack: str) -> list[ConfigFlawFinding]:
    repo = Path(repo_path)
    if not repo.is_dir():
        logger.error("config_flaws.not_a_directory", path=repo_path)
        return []

    all_findings = []
    for analyzer in ANALYZERS:
        try:
            findings = analyzer(repo)
            all_findings.extend(findings)
        except Exception as e:
            logger.warning("config_flaws.analyzer_failed", analyzer=analyzer.__name__, error=str(e))

    logger.info("config_flaws.done", repo=repo_path, total=len(all_findings))
    return all_findings
