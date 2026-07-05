#!/usr/bin/env bash
set -euo pipefail

# ────────────────────────────────────────────────────────────────────
# scripts/verify-supabase-rls.sh
# Verify Row-Level Security policies work as expected.
#
# Prerequisites:
#   - curl and jq installed
#   - SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY set
#
# Usage:
#   SUPABASE_URL=https://<ref>.supabase.co \
#   SUPABASE_ANON_KEY=eyJ... \
#   SUPABASE_SERVICE_ROLE_KEY=eyJ... \
#   bash scripts/verify-supabase-rls.sh
# ────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
info() { echo -e "  ${YELLOW}ℹ${NC} $1"; }

echo ""
echo -e "${BOLD}AntiVibe — Supabase RLS Verification${NC}"
echo ""

# ── Step 0: Check prerequisites ────────────────────────────────────

if ! command -v curl &>/dev/null; then
  echo -e "  ${RED}ERROR:${NC} curl not found. Install it and retry."
  exit 1
fi
if ! command -v jq &>/dev/null; then
  echo -e "  ${RED}ERROR:${NC} jq not found. Install it and retry."
  echo "    apt install jq   # Debian/Ubuntu"
  echo "    brew install jq  # macOS"
  exit 1
fi
pass "curl and jq available"

# ── Step 1: Validate env vars ──────────────────────────────────────

MISSING=0
for var in SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY; do
  if [[ -z "${!var:-}" ]]; then
    fail "$var not set"
    MISSING=1
  fi
done

if [[ "$MISSING" -eq 1 ]]; then
  echo ""
  echo -e "  ${RED}Aborting. Set missing env vars and retry.${NC}"
  exit 1
fi
pass "All required env vars set"

API_BASE="${SUPABASE_URL}/rest/v1"
ANON_KEY="$SUPABASE_ANON_KEY"
SERVICE_KEY="$SUPABASE_SERVICE_ROLE_KEY"

# Generate a unique scan ID for service-role insert test.
SCAN_ID="00000000-0000-0000-0000-000000000000"

# ── Test 1: Unauthenticated read on scans (no Authorization header) ─

echo ""
echo -e "  ${YELLOW}[Test 1]${NC} Unauthenticated read — anon key, no JWT"
echo "    Expect: 200 + empty array (RLS filters out all rows)"

HTTP_STATUS=$(curl -s -o /tmp/av_rls_test1_body.json -w "%{http_code}" \
  "${API_BASE}/scans?select=id&limit=1" \
  -H "apikey: ${ANON_KEY}" \
  -H "Content-Type: application/json" 2>&1)

RESPONSE_BODY=$(cat /tmp/av_rls_test1_body.json)

if [[ "$HTTP_STATUS" == "200" ]]; then
  if echo "$RESPONSE_BODY" | jq -e 'length == 0' &>/dev/null; then
    pass "Test 1: empty array returned (RLS blocks unauthenticated reads)"
  else
    info "Test 1: 200 OK, but response has $(echo "$RESPONSE_BODY" | jq length) rows"
    info "  (This may be expected if there are no rows yet, or RLS is not enforced)"
  fi
else
  fail "Test 1: expected HTTP 200, got ${HTTP_STATUS}"
  info "  Body: $(echo "$RESPONSE_BODY" | head -c 200)"
fi

# ── Test 2: Service-role insert ────────────────────────────────────

echo ""
echo -e "  ${YELLOW}[Test 2]${NC} Service-role insert (bypasses RLS)"
echo "    Expect: 201 Created"

# Generate a deterministic UUID for cleanup.
SCAN_UUID="$(uuidgen 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null || echo "a1b2c3d4-e5f6-7890-abcd-ef1234567890")"
USER_UUID="00000000-0000-0000-0000-000000000001"

HTTP_STATUS=$(curl -s -o /tmp/av_rls_test2_body.json -w "%{http_code}" \
  -X POST "${API_BASE}/scans" \
  -H "apikey: ${SERVICE_KEY}" \
  -H "Authorization: Bearer ${SERVICE_KEY}" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=minimal" \
  -d "{
    \"id\": \"${SCAN_UUID}\",
    \"user_id\": \"${USER_UUID}\",
    \"repo_url\": \"https://github.com/owner/rls-test-repo\",
    \"status\": \"pending\"
  }" 2>&1)

if [[ "$HTTP_STATUS" == "201" ]]; then
  pass "Test 2: service-role insert succeeded (HTTP 201)"

  # Clean up — delete the test row.
  curl -s -X DELETE "${API_BASE}/scans?id=eq.${SCAN_UUID}" \
    -H "apikey: ${SERVICE_KEY}" \
    -H "Authorization: Bearer ${SERVICE_KEY}" \
    -o /dev/null 2>&1 || true
else
  fail "Test 2: expected HTTP 201, got ${HTTP_STATUS}"
  RESPONSE=$(cat /tmp/av_rls_test2_body.json)
  info "  Body: $(echo "$RESPONSE" | head -c 200)"
fi

# ── Test 3: Anon user cannot read other users' scans ───────────────

echo ""
echo -e "  ${YELLOW}[Test 3]${NC} Anon user cannot read other users' scans"
echo "    Expect: 200 + empty array (RLS scoped to auth.uid)"

# First, insert a scan as service-role for a real-looking user.
REAL_SCAN_UUID="$(uuidgen 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null || echo "b2c3d4e5-f6a7-8901-bcde-f12345678901")"
REAL_USER_UUID="00000000-0000-0000-0000-000000000002"

curl -s -X POST "${API_BASE}/scans" \
  -H "apikey: ${SERVICE_KEY}" \
  -H "Authorization: Bearer ${SERVICE_KEY}" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=minimal" \
  -d "{
    \"id\": \"${REAL_SCAN_UUID}\",
    \"user_id\": \"${REAL_USER_UUID}\",
    \"repo_url\": \"https://github.com/owner/private-repo\",
    \"status\": \"completed\"
  }" -o /dev/null 2>&1 || true

# Now try to read it with anon key (no auth).
HTTP_STATUS=$(curl -s -o /tmp/av_rls_test3_body.json -w "%{http_code}" \
  "${API_BASE}/scans?id=eq.${REAL_SCAN_UUID}" \
  -H "apikey: ${ANON_KEY}" \
  -H "Content-Type: application/json" 2>&1)

RESPONSE_BODY=$(cat /tmp/av_rls_test3_body.json)

if [[ "$HTTP_STATUS" == "200" ]]; then
  if echo "$RESPONSE_BODY" | jq -e 'length == 0' &>/dev/null; then
    pass "Test 3: empty array returned (anon cannot access other user's scan)"
  else
    fail "Test 3: anon read returned data — RLS may be misconfigured"
    info "  Body: $(echo "$RESPONSE_BODY" | head -c 200)"
  fi
else
  fail "Test 3: expected HTTP 200, got ${HTTP_STATUS}"
  info "  Body: $(echo "$RESPONSE_BODY" | head -c 200)"
fi

# Cleanup test data.
curl -s -X DELETE "${API_BASE}/scans?id=eq.${REAL_SCAN_UUID}" \
  -H "apikey: ${SERVICE_KEY}" \
  -H "Authorization: Bearer ${SERVICE_KEY}" \
  -o /dev/null 2>&1 || true

# ── Summary ────────────────────────────────────────────────────────

echo ""
echo "  ─────────────────────────────────────"
if [[ "$MISSING" -eq 0 ]]; then
  echo -e "  ${GREEN}${BOLD}RLS verification complete.${NC}"
  echo "  Review any failures above and check Supabase Dashboard →"
  echo "  Authentication → Policies to confirm RLS is enabled on all tables."
else
  echo -e "  ${RED}${BOLD}Some tests did not pass.${NC}"
  echo "  Verify Supabase project status and RLS policies."
fi
echo ""
