# Feature: Supabase Schema

**Purpose:** Initialize Supabase Postgres project w/ full schema (users/scans/findings/reports/oauth_tokens/webhook_deliveries/subscriptions/scan_usage/sandbox_egress_log) + RLS policies + Storage buckets.
**Wave:** 1  **Owner task:** 3  **Status:** pending

## Public API
- `migrations/0001_init.sql` — idempotent DDL applied via `psql` or `supabase db push`
- `apps/dashboard/lib/supabase/client.ts` exports `createBrowserClient()` (anon key only)
- `apps/dashboard/lib/supabase/server.ts` exports `createServerClient()` (service role when needed; else uses RLS w/ user's JWT)
- `services/sandbox-svc/sb_client.py` exports `SupabaseClient` (server-side only, service-role)

## Internal flow
1. Author writes `migrations/0001_init.sql` per `docs/data-model.md` spec (8 base tables; 9th `sandbox_egress_log` added in Task 18)
2. Enable RLS on all tables
3. Create policies per data-model spec (owner_select/owner_insert/owner_update via `auth.uid()`)
4. Apply migration against local Supabase (Docker) or hosted Supabase via `psql "$DB_URL" -f migrations/0001_init.sql`
5. Generate types: `pnpm exec supabase gen types typescript --local > packages/shared-types/src/supabase.ts`
6. Create Storage buckets via Supabase dashboard (manual) or migration: `scan-artifacts` (private), `poc-captures` (private)

## Inputs
- Supabase project URL + anon key + service role key (env vars)
- `docs/data-model.md` as schema spec

## Outputs
- 8 tables created w/ RLS enabled
- 2 private storage buckets
- Generated `supabase.ts` types file under `packages/shared-types`

## Acceptance criteria
- [ ] `migrations/0001_init.sql` runs cleanly on fresh Postgres
- [ ] Vitest `tests/rls.test.ts` proves cross-user read rejection (user A's scan invisible to user B)
- [ ] RLS enabled on every table (`pg_class.relrrowsecurity = true`)
- [ ] `lib/supabase/server.ts` returns typed client satisfying generated `Db` schema type
- [ ] Bucket metadata `public = false`

## Test plan
```
Scenario: RLS blocks cross-user scans
  Steps: psql -f migrations/0001_init.sql; signup user A + user B; TOKEN_A inserts scan; TOKEN_B GET /rest/v1/scans
  Expected: A gets 201; B gets []
  Evidence: .omo/evidence/task-3-rls-blocks.txt

Scenario: Service-role never shipped to browser bundle
  Steps: pnpm build; grep "SUPABASE_SERVICE_ROLE" apps/dashboard/.next/static
  Expected: 0 matches
  Evidence: .omo/evidence/task-3-no-service-role-in-bundle.txt
```

## Cross-references
- [see data-model.md#table-specs]
- [see data-model.md#rls-policy-spec]
- [see security-threat-model.md#tampering]
- [see system-design.md#supabase-schema-conventions]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |