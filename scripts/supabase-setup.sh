#!/usr/bin/env bash
set -euo pipefail

# ────────────────────────────────────────────────────────────────────
# scripts/supabase-setup.sh
# Provision the AntiVibe Supabase project schema.
#
# Prerequisites:
#   - psql (PostgreSQL client) installed
#   - SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars set
#
# Usage:
#   SUPABASE_URL=https://db.xxxxx.supabase.co \
#   SUPABASE_SERVICE_ROLE_KEY=eyJ... \
#   bash scripts/supabase-setup.sh
# ────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }

# ── Step 0: Check prerequisites ────────────────────────────────────

echo ""
echo -e "${BOLD}AntiVibe — Supabase Setup${NC}"
echo ""

if ! command -v psql &>/dev/null; then
  echo -e "  ${RED}ERROR:${NC} psql not found. Install PostgreSQL client:"
  echo "    apt install postgresql-client   # Debian/Ubuntu"
  echo "    brew install libpq              # macOS"
  echo "    choco install postgresql        # Windows (Chocolatey)"
  exit 1
fi
pass "psql available"

# ── Step 1: Validate env vars ──────────────────────────────────────

MISSING=0
if [[ -z "${SUPABASE_URL:-}" ]]; then
  fail "SUPABASE_URL not set"
  MISSING=1
else
  pass "SUPABASE_URL is set"
fi

if [[ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]]; then
  fail "SUPABASE_SERVICE_ROLE_KEY not set"
  MISSING=1
else
  pass "SUPABASE_SERVICE_ROLE_KEY is set"
fi

if [[ "$MISSING" -eq 1 ]]; then
  echo ""
  echo -e "  ${RED}Aborting. Set missing env vars and retry.${NC}"
  echo "  See env.template for details."
  exit 1
fi

# ── Step 2: Resolve connection string ──────────────────────────────
# SUPABASE_URL format: https://<project-ref>.supabase.co
# Build pooler connection string:
#   postgresql://service_role:<key>@aws-0-<ref>.pooler.supabase.com:6543/postgres

PROJECT_REF=$(echo "$SUPABASE_URL" | sed -E 's|https?://([^.]+)\..*|\1|')

if [[ -z "$PROJECT_REF" || "$PROJECT_REF" == "$SUPABASE_URL" ]]; then
  echo ""
  echo -e "  ${RED}ERROR:${NC} Could not parse project ref from SUPABASE_URL."
  echo "    Expected format: https://<project-ref>.supabase.co"
  echo "    Got:            $SUPABASE_URL"
  exit 1
fi

# Transaction pooler (port 6543) — preferred for migration runs.
CONN_STRING="postgresql://service_role:${SUPABASE_SERVICE_ROLE_KEY}@aws-0-${PROJECT_REF}.pooler.supabase.com:6543/postgres"
# Fallback direct connection (port 5432).
CONN_STRING_SESSION="postgresql://service_role:${SUPABASE_SERVICE_ROLE_KEY}@${PROJECT_REF}.supabase.co:5432/postgres"

pass "Connection string resolved (project: ${PROJECT_REF})"

# ── Step 3: Locate migration file ──────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATION_FILE="${PROJECT_DIR}/migrations/0001_init.sql"

if [[ ! -f "$MIGRATION_FILE" ]]; then
  echo ""
  echo -e "  ${RED}ERROR:${NC} Migration file not found at:"
  echo "    $MIGRATION_FILE"
  exit 1
fi
pass "Migration file found: migrations/0001_init.sql"

# ── Step 4: Apply migration ────────────────────────────────────────

echo ""
echo -e "  ${YELLOW}Applying migration...${NC}"

PG_OUTPUT=""
if PG_OUTPUT=$(psql "$CONN_STRING" -f "$MIGRATION_FILE" -v ON_ERROR_STOP=1 2>&1); then
  pass "Migration applied via transaction pooler"
elif PG_OUTPUT=$(psql "$CONN_STRING_SESSION" -f "$MIGRATION_FILE" -v ON_ERROR_STOP=1 2>&1); then
  pass "Migration applied via direct connection (pooler unavailable)"
else
  echo ""
  echo -e "  ${RED}ERROR:${NC} Migration failed. psql output:"
  echo "$PG_OUTPUT" | sed 's/^/    /'
  echo ""
  echo "  Possible causes:"
  echo "    - Supabase project does not exist or is paused"
  echo "    - SUPABASE_SERVICE_ROLE_KEY is invalid or expired"
  echo "    - IP not allowed (check Supabase Dashboard → Database → Network Restrictions)"
  echo "    - Connection pooler is down (retry with direct connection)"
  exit 1
fi

# ── Step 5: Verify tables ──────────────────────────────────────────

echo ""
echo -e "  ${YELLOW}Verifying tables...${NC}"

EXPECTED_TABLES=(
  "users"
  "scans"
  "findings"
  "reports"
  "oauth_tokens"
  "webhook_deliveries"
  "subscriptions"
  "scan_usage"
  "sandbox_egress_log"
)

# Query existing tables via psql.
EXISTING_TABLES=$(psql "$CONN_STRING" -t -A -c "
  SELECT tablename
  FROM pg_catalog.pg_tables
  WHERE schemaname = 'public'
  ORDER BY tablename;
" 2>/dev/null) || EXISTING_TABLES=$(psql "$CONN_STRING_SESSION" -t -A -c "
  SELECT tablename
  FROM pg_catalog.pg_tables
  WHERE schemaname = 'public'
  ORDER BY tablename;
" 2>/dev/null) || {
  echo ""
  echo -e "  ${RED}ERROR:${NC} Could not query table list after migration."
  echo "    Connection may have dropped. Verify manually via Supabase dashboard."
  exit 1
}

ALL_OK=0
for tbl in "${EXPECTED_TABLES[@]}"; do
  if echo "$EXISTING_TABLES" | grep -qx "$tbl"; then
    pass "public.${tbl} exists"
  else
    fail "public.${tbl} missing"
    ALL_OK=1
  fi
done

# ── Report ──────────────────────────────────────────────────────────

echo ""
if [[ "$ALL_OK" -eq 0 ]]; then
  echo -e "  ${GREEN}${BOLD}✓ All 9 tables verified. Supabase setup complete.${NC}"
else
  echo -e "  ${RED}${BOLD}✗ Some tables are missing. Check migration output above.${NC}"
  exit 1
fi

echo ""
echo "  Next steps:"
echo "    1. Create storage buckets via Supabase Dashboard:"
echo "       - scan-artifacts (private)"
echo "       - poc-captures (private)"
echo "    2. Run scripts/verify-supabase-rls.sh to confirm RLS policies"
echo ""
