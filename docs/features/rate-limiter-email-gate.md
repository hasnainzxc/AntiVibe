# Feature: Rate Limiter + Email Verification Gate

**Purpose:** Next.js middleware gating `/api/scan` POST: 1 scan / hour / IP+user, AND email verification required before free scans.
**Wave:** 1  **Owner task:** 7  **Status:** pending

## Public API
```ts
// apps/dashboard/middleware.ts
export default async function middleware(req: NextRequest): Promise<NextResponse>
export const config = { matcher: ['/api/scan'] }
```

## Internal flow
1. Match `/api/scan`
2. Get session via `getSession()` helper
3. Compute key = `rate:scan:${user_id}:${ip}`
4. Redis INCR via Upstash REST API (window 1h)
5. If count > 1 → return 429 + `Retry-After: <seconds_left>`
6. If user.email_verified_at IS NULL → return 403 + `{ error: { code: 'email_not_verified' } }`
7. Fallback to in-memory Map if Redis env unset (dev mode)

## Inputs
- Supabase JWT (via cookie or Authorization header)
- User IP (via `x-forwarded-for`)
- Upstash Redis (env `UPSTASH_REDIS_REST_URL`, optional for dev)

## Outputs
- 429 OR 403 OR pass-through to handler
- `Retry-After` header (seconds, integer) on 429

## Acceptance criteria
- [ ] 2nd scan in 1h from same user+IP blocked w/ 429 + `Retry-After`
- [ ] Unverified email returns 403 w/ `reason: 'email_not_verified'`
- [ ] Vitest middleware tests pass (4 cases: verified/limit-OK/limit-exceeded/unverified)
- [ ] Other routes (e.g., `/api/scans`) NOT affected (only `/api/scan` POST)

## Test plan
```
Scenario: 2nd scan in 1 hour blocked
  Steps: 2× curl -X POST localhost:3000/scan -F repo=... -H "Cookie: ..."
  Expected: 200 then 429 + Retry-After: ~3600
  Evidence: .omo/evidence/task-7-rate-limit.txt

Scenario: Unverified email blocked
  Steps: signin w/ email_verified_at=null; curl -X POST localhost:3000/scan
  Expected: 403 + {"reason":"email_not_verified"}
  Evidence: .omo/evidence/task-7-email-gate.txt
```

## Cross-references
- [see api-spec.md#post-apiscan]
- [see security-threat-model.md#denial-of-service]
- [see billing-and-pricing.md#plans]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |