# AntiVibe — API Spec

**Purpose:** REST contract between Next.js Dashboard ↔ SaaS FastAPI service ↔ external clients (GitHub webhooks, Stripe webhooks).
**Last Updated:** 2026-07-04
**Owner:** AntiVibe solo-founder

## Base URLs

| Surface | Base URL | Auth |
|---------|----------|------|
| Public dashboard API | `https://antivibe.app/api/*` (Next.js Route Handlers exposed by dashboard) | Supabase access JWT in `Authorization: Bearer <jwt>` + Supabase RLS enforced server-side |
| Sandbox-svc internal | `http://sandbox-svc.internal:8000/v1/*` (FastAPI; not exposed to public) | mTLS between Fly machines (Fly internal network) |
| Webhooks | `https://antivibe.app/api/webhooks/{provider}` | HMAC-SHA256 signature from provider |

## Auth

- All authenticated endpoints require `Authorization: Bearer <supabase_access_jwt>`
- Server-side validates JWT via Supabase Auth helper (`@supabase/ssr` for dashboard; `supabase-py` for sandbox-svc)
- RLS enforced by Supabase Postgres — user can ONLY see their own scans/findings/reports/oauth_tokens/subscriptions
- Webhook endpoints authenticate via HMAC-SHA256 signature from GitHub/Stripe (NOT Supabase JWT)

## Endpoints

### `POST /api/scan` — start scan
- **Body**: `{ "repo_url": string, "branch"?: string, "full_scan"?: boolean }`
- **Auth**: required
- **Rate limit**: 1 scan/hour/IP+user (returns 429 + `Retry-After` header on hit)
- **Email gate**: 403 if user.email_verified_at IS NULL
- **Returns**:
  - 201: `{ "scan_id": uuid }`
  - 403: `{ "error": { "code": "email_not_verified", "message": "Verify your email to trigger scans" } }`
  - 429: `{ "error": { "code": "rate_limited", "message": "1 scan/hour max", "retry_after": 3600 } }`
  - 401: `{ "error": { "code": "unauthorized" } }`

### `GET /api/scan/:id` — poll scan status
- **Returns**: scan row + nested findings (paginated, default 50/page)
- **Statuses**: pending, cloning, detected, tier1_running, tier2_running, tier3_running, normalizing, done, partial, failed
- **Side effects**: increments no-op可以从:TBD tracking of poll count for abuse detection

### `GET /api/scan/:id/report` — fetch report
- **Returns**: `{ "scan_id": uuid, "markdown": string, "json": object, "artifact_url": signed_url (60min) }`
- **Content-Type**: application/json OR text/plain (accept header)
- **Status**: 404 if no report yet (scan incomplete)

### `GET /api/scans` — list user's scans
- **Query**: `?page=1&limit=20&status=done`
- **Rate limit**: 60 req/min/IP

### `POST /api/billing/checkout` — start Checkout session
- **Body**: `{ "tier": "indie"|"pro" }`
- **Returns**: `{ "checkout_url": string }`
- **Provider**: Stripe Checkout or LemonSqueezy Checkout (decided task 38)

### `POST /api/billing/portal` — Stripe portal session
- **Returns**: `{ "portal_url": string }`

### `GET /api/usage` — current month's scan count + tier
- **Returns**: `{ "tier": "free"|"indie"|"pro", "scans_used": int, "scans_limit": int, "month": "YYYY-MM" }`

### `POST /api/webhooks/github` — GitHub webhook receiver
- **No auth header** — signature verified via `x-hub-signature-256` HMAC-SHA256 vs `GITHUB_WEBHOOK_SECRET`
- **Headers**: `x-github-event`, `x-github-delivery` (idempotency key)
- **Events handled**: `push` (trigger scan on pushed ref if repo connected), `installation_repositories` (update user's connected repos)
- **Returns**: 200 always (don't leak to GitHub)
- **Idempotent**: event_id stored in `webhook_deliveries` table; retry ignored

### `POST /api/webhooks/stripe` — Stripe webhook
- **No auth header** — verified via `Stripe-Signature` header vs `STRIPE_WEBHOOK_SECRET`
- **Events handled**: `checkout.session.completed` (升级 tier), `customer.subscription.deleted` (downgrade), `invoice.payment_failed` (email user)
- **Idempotent**: event_id stored in `webhook_deliveries`
- **Lemon Squeezy alternative endpoint**: `/api/webhooks/lemonsqueezy` (same shape, different secret)

### `GET /api/repos` — list user's connected GitHub repos
- **Auth**: required + `oauth_tokens.provider='github'` row present
- **Returns**: array of `{ owner, repo, last_scanned_at? }`

### `POST /api/github/connect` — initiate GitHub OAuth flow
- **Returns**: `{ "redirect_url": string }` (github.com/login/oauth/authorize?...)
- **After OAuth callback**: `GET /api/github/callback?code=...` stores token in `oauth_tokens`

### `DELETE /api/github/disconnect` — revoke GitHub OAuth
- **Returns**: 204
- **Side effects**: revokes GitHub token via `DELETE https://api.github.com/applications/{client_id}/grant`; deletes `oauth_tokens` row

## Error Envelope

```json
{ "error": { "code": "string", "message": "string", "retry_after"?: int } }
```

### Error Code Reference

| Code | HTTP | Meaning | Retry? |
|------|------|---------|--------|
| `unauthorized` | 401 | Missing/invalid JWT | No |
| `forbidden` | 403 | RLS rejects access | No |
| `email_not_verified` | 403 | User.email_verified_at null | No |
| `rate_limited` | 429 | Hit rate limit | Yes, after `retry_after` |
| `not_found` | 404 | Resource doesn't exist (or not owned) | No |
| `repo_too_large` | 422 | Repo >500MB | No |
| `unsupported_stack` | 422 | Stack not in whitelist | No |
| `circuit_breaker` | 503 | Scan hit 10min or $0.50 cap; partial report emitted | No |
| `provider_down` | 503 | Anthropic/Fly/Stripe down | Yes (exponential backoff) |
| `internal_error` | 500 | Unexpected | Yes max 3 |

## Rate Limits

| Endpoint | Limit | Key |
|----------|-------|-----|
| `/api/scan` (POST) | 1/hour | user_id + ip |
| `/api/scans` (GET) | 60/min | ip |
| `/api/scan/:id` (GET) | 120/min | user_id |
| All webhooks | 100/sec per source | source (GitHub IP ranges mapped to source; Stripe IP ranges) |

## Idempotency

- GitHub webhook events deduped via `webhook_deliveries.event_id` (`x-github-delivery` header)
- Stripe webhook events deduped via `webhook_deliveries.event_id` (`Stripe-Signature`'s event id from the payload)
- Scan triggers from webhook include `idempotency_key = webhook_event_id + ":" + repo_url` so duplicate webhook retriggers don't double-scan

## Status

| Endpoint | Impl? | Tests? | Owner Task |
|----------|-------|--------|-----------|
| POST /api/scan | pending | pending | Task 43 |
| GET /api/scan/:id | pending | pending | Task 36/37 |
| GET /api/scans | pending | pending | Task 36 |
| POST /api/billing/checkout | pending | pending | Task 38 |
| POST /api/webhooks/github | pending | pending | Task 35 |
| POST /api/webhooks/stripe | pending | pending | Task 38 |
| GET /api/usage | pending | pending | Task 44 |
| POST /api/github/connect | pending | pending | Task 34 |
| POST /api/github/callback | pending | pending | Task 34 |
| DELETE /api/github/disconnect | pending | pending | Task 34 |