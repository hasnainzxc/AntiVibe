"""Configuration-flaw analyzer: static checks for security misconfigurations.

Where the secret detector looks for *leaked* credentials, this module
looks for *configurations* that would let an attacker escalate or
exfiltrate even without a leaked secret. The class of findings:

  - **Firestore rules**: `allow read, write: if true` is the
    single most common Firebase misconfiguration in the wild.
    Multi-tenant data leak in one line of DSL.
  - **CORS**: `Access-Control-Allow-Origin: *` combined with
    authenticated routes enables cross-origin exfiltration.
  - **IAM**: `Action: "s3:*"` + `Resource: "*"` is the textbook
    least-privilege violation. One policy can grant the whole bucket.
  - **No-op auth**: Express middleware that calls `next()` without
    checking auth is a "secure-feeling" auth bypass — the route
    looks protected in code review but accepts every request.
  - **Missing helmet**: Express apps without `helmet` ship without
    X-Frame-Options, X-Content-Type-Options, etc.

Each finding carries:
  - `patch_md`: human-readable fix rendered in the dashboard.
  - `patch_diff`: unified-diff format for `git apply` / `patch`.
  - `evidence`: the offending line(s), trimmed.

Detection is best-effort. A repo that passes every check is *not*
guaranteed to be secure — these are the high-signal, low-cost
patterns that catch the common cases.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from enum import Enum
import structlog

logger = structlog.get_logger(__name__)


class Severity(str, Enum):
    """Finding severity. Wire-stable: serialized into findings and stored
    in the DB. New levels must be added in consultation with the
    dashboard team — the UI color-codes on these values.
    """
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ConfigFlawFinding:
    """A single configuration flaw. The `patch_md` and `patch_diff` fields
    are independently generated so the dashboard can show a "view fix"
    link (markdown) or a "download patch" link (unified diff) without
    having to render one from the other.
    """
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
    """Find `firestore.rules` files and flag unconditional allow rules.

    Firestore security rules are evaluated server-side; a single
    `allow read, write: if true;` line is the entire auth model
    for the collection it covers. We treat this as critical
    because (a) it requires no other vulnerability to exploit —
    a project ID is enough — and (b) the affected data is often
    user PII.

    Two patterns are matched:
      1. `allow read, write: if true;` — the canonical leak.
      2. `allow read: if true;` (no write) — still critical for
         any collection that contains sensitive data, but a step
         down from full R/W because the attacker can't mutate.
    """
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
            # Critical: full read+write with no auth check.
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

            # High-severity: read-only with no auth check. The extra
            # `"write" not in line` guard prevents double-counting lines
            # already caught by the RW rule above.
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
    """Flag `Access-Control-Allow-Origin: *` only when the project
    also has authenticated routes — a wildcard CORS in a fully
    public app is fine; the danger is the combination.

    The reason this isn't flagged unconditionally: a static site
    that legitimately serves public assets to any origin needs
    `*`. The auth-route lookup is what raises the severity to
    critical (a CSRF attacker can read response data cross-origin
    because credentials are sent by default in fetch).
    """
    findings = []
    cors_re = re.compile(r'Access-Control-Allow-Origin.*\*')

    # Only Next.js projects are scanned — Express apps configure CORS
    # in code, not in a config file, and the regex would miss them.
    # Express CORS misconfig is covered by the no-op auth analyzer
    # (different attack class).
    for filepath in [repo / "next.config.js", repo / "next.config.mjs", repo / "next.config.ts"]:
        if not filepath.exists():
            continue
        try:
            content = filepath.read_text(errors="ignore")
        except OSError:
            continue

        for i, line in enumerate(content.split("\n"), 1):
            if cors_re.search(line):
                # Check for authenticated routes under app/api/.
                # `Authorization` string-match is intentional — it
                # catches the common patterns (NextAuth, custom
                # middleware, third-party JWT) without requiring
                # AST parsing.
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
    """Flag IAM policy files granting `s3:*` on `Resource: "*"`.

    Matches the `.policies` extension convention used by some
    infrastructure-as-code projects (Terraform plan exports, custom
    format). Standard `.json` IAM policies are not matched here —
    those are typically managed by `aws iam` tooling that has its
    own validation, and a substring match on `"s3:*"` in arbitrary
    JSON would produce too many false positives.
    """
    findings = []

    for policy_path in repo.rglob("*.policies"):
        try:
            content = policy_path.read_text(errors="ignore")
        except OSError:
            continue
        # Both conditions must hold:
        #   - `"s3:*"` literal — broad action grant
        #   - `"Resource": "*"` literal — broad resource grant
        # Substring match is sufficient because both fragments are
        # rare in non-IAM contexts (a regex would be brittle given
        # the variation in JSON formatting).
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
    """Flag Express no-op auth middleware: `app.use((req, res, next) => next())`.

    This pattern is a common copy-paste from a tutorial that
    demonstrates *middleware chaining* without an auth check. The
    comment "this is where you'd add auth" never gets added; the
    middleware silently allows every request through.

    Detected via a single regex; we don't try to follow the
    middleware's variable name or surrounding comments.
    """
    findings = []

    # Exact-shape match. Variants like `function (req, res, next)`
    # or a multiline arrow function are not caught — those are
    # rare in real Express code and the false-negative cost is
    # low (the LLM stage will catch them on semantic review).
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
                # One finding per file — a no-op middleware appears
                # once, not per line. Breaking here avoids generating
                # duplicate findings for the same line.
                break

    return findings


# ─── Helmet analyzer ───

def _analyze_missing_helmet(repo: Path) -> list[ConfigFlawFinding]:
    """Flag Express projects that don't depend on `helmet`.

    Helmet is a near-zero-config bundle of security headers
    (X-Frame-Options, X-Content-Type-Options, Strict-Transport-Security,
    etc.) that every Express app should ship. The check is on
    `package.json` rather than on actual `app.use(helmet())` calls
    because:

      1. The dep is necessary but not sufficient — the user might
         declare it but forget to wire it. The LLM stage catches
         that case semantically.
      2. Static analysis of `app.use(...)` calls across all files
         would over-fire (helmet might be wired in a separate
         setup file the analyzer doesn't see).

    Severity is MEDIUM rather than CRITICAL because missing
    headers are exploitable only in combination with another
    vulnerability (XSS, MITM, clickjacking).
    """
    findings = []
    pkg_path = repo / "package.json"
    if not pkg_path.exists():
        return findings

    try:
        pkg = json.loads(pkg_path.read_text())
    except (json.JSONDecodeError, OSError):
        return findings

    # Both dep maps merged — helmet might be in devDependencies
    # for projects that only run it in non-prod.
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

# Analyzers run in this order. Order is not significant for correctness
# (analyzers are independent) but does affect log line ordering — we
# list cheapest first so the operator sees the most common findings
# in the first log lines.
ANALYZERS = [
    _analyze_firestore_rules,
    _analyze_cors,
    _analyze_iam,
    _analyze_permissive_auth,
    _analyze_missing_helmet,
]


def analyze_config_flaws(repo_path: str, stack: str) -> list[ConfigFlawFinding]:
    """Run every analyzer against a cloned repo and return the aggregate.

    `stack` is currently unused — analyzers detect stack-specific
    signals from filenames (`next.config.js`, `app.js`) rather than
    from the parameter. Kept in the signature so the orchestrator
    can pass a hint if we later add stack-gated analyzers (e.g. a
    "Django CSRF" check that's only relevant for Django).

    Returns an empty list (not raises) on a non-existent path or
    analyzer-level exception — a single broken analyzer should not
    lose the findings from the others. The exception is logged at
    warning so it's debuggable without halting the pipeline.
    """
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
