/**
 * Next.js edge middleware: per-IP+user scan rate limit + email-verification gate.
 *
 * Runs in the Vercel Edge runtime (or any Next-compatible edge). The store is
 * intentionally in-process; the trade-off is documented in `WINDOW_MS` below.
 *
 * Security boundary:
 *   - This file is loaded for every request matching `config.matcher`. The
 *     matcher intentionally narrows to /scan so that auth refreshes and
 *     other heavy traffic don't pay the rate-limit cost.
 *   - `x-email-verified` is set upstream by the Supabase SSR cookie auth
 *     check in the page server component; we only re-assert it here as a
 *     defense-in-depth gate, not as the primary source of truth.
 *
 * Algorithm choice — fixed window over sliding window:
 *   Fixed window was picked over sliding-log because:
 *     1. O(1) memory per key and O(1) time per check. A sliding window would
 *        require either a Redis sorted set (operational dependency) or a
 *        client-side log per key (memory blow-up under attack).
 *     2. Edge runtime cannot reach Redis over TCP without an extra service.
 *     3. The 1h window is coarse enough that burst-at-the-boundary issues
 *        (worst case 2x the limit at the rollover) are tolerable for a
 *        scan endpoint that is throttled by tier cost anyway.
 *   Trade-off: an attacker can fire MAX_REQUESTS at second 3599 and again at
 *   second 0. Acceptable for a paid scan endpoint; revisit if abused.
 *
 * InMemoryStore fallback vs Redis:
 *   This module is the in-memory fallback. Production deployment MUST front
 *   this with a Redis-backed limiter (e.g. Upstash) before scaling beyond a
 *   single region — otherwise the limit is per-process, not per-user. The
 *   `rateLimitMap` shape is a deliberate subset of the Redis API so a swap
 *   to a `INCR` + `EXPIRE` implementation drops in without touching callers.
 *
 * Error envelope:
 *   The 429/403 bodies match the shared `ApiError` contract from
 *   `@antivibe/shared-types` — `{ error: { code, message, retry_after? } }`.
 *   The Retry-After header is also set per RFC 6585 so well-behaved clients
 *   back off correctly without parsing the body.
 */

import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

// In-memory store for rate limiting (fallback when no Redis configured).
// Production should swap to Upstash/Redis — see module doc above.
const rateLimitMap = new Map<string, { count: number; resetAt: number }>()

// 1h fixed window. Long enough that a user retrying a failed scan doesn't
// feel locked out, short enough to bound the worst-case scan cost per user.
const WINDOW_MS = 60 * 60 * 1000
// 1 scan per hour per IP+user. Matches the FREE tier in
// `subscriptions.scan_usage.scans_limit`; the middleware is the first line,
// the DB is the source of truth.
const MAX_REQUESTS = 1

function getRateLimitKey(request: NextRequest): string {
  // `x-forwarded-for` is a comma-separated chain set by the load balancer; the
  // first entry is the original client. Falls back to x-real-ip, then to a
  // loopback literal so a misconfigured proxy still gets a stable per-key rate.
  const ip = request.headers.get('x-forwarded-for')?.split(',')[0]?.trim()
    || request.headers.get('x-real-ip')
    || '127.0.0.1'
  // Slice(0, 16) of the JWT gives a stable per-user bucket without storing
  // the full token. We do NOT trust this for auth — Supabase SSR validates
  // the token signature server-side. The slice is only for key cardinality.
  const userId = request.cookies.get('sb-access-token')?.value?.slice(0, 16) || 'anon'
  return `${ip}:${userId}:scan`
}

function checkRateLimit(key: string): { allowed: boolean; retryAfter?: number } {
  const now = Date.now()
  const entry = rateLimitMap.get(key)

  if (!entry || now > entry.resetAt) {
    // First request in window (or window expired). Initialize and allow.
    rateLimitMap.set(key, { count: 1, resetAt: now + WINDOW_MS })
    return { allowed: true }
  }

  if (entry.count >= MAX_REQUESTS) {
    // Compute retry-after in seconds, rounded up. Clients should treat this
    // as a lower bound; the actual unlock is `entry.resetAt`.
    const retryAfter = Math.ceil((entry.resetAt - now) / 1000)
    return { allowed: false, retryAfter }
  }

  entry.count++
  return { allowed: true }
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  // Matcher config below scopes middleware to /scan; this guard is belt-and-
  // suspenders in case the matcher is widened in the future. POST only — GETs
  // (e.g. the page render) pass through to the route handler untouched.
  if (pathname === '/scan' && request.method === 'POST') {
    const key = getRateLimitKey(request)
    const { allowed, retryAfter } = checkRateLimit(key)

    if (!allowed) {
      // Body shape matches `ApiError` from @antivibe/shared-types. Do not
      // add fields — clients parse this with the shared type guard.
      return NextResponse.json(
        { error: { code: 'rate_limited', message: 'Too many scans. Please wait.', retry_after: retryAfter } },
        {
          status: 429,
          headers: {
            // Standard + de-facto-standard rate-limit headers. Both Retry-After
            // and X-RateLimit-Remaining are emitted so SDKs and curl users
            // both back off correctly.
            'Retry-After': String(retryAfter),
            'X-RateLimit-Limit': String(MAX_REQUESTS),
            'X-RateLimit-Remaining': '0',
          },
        }
      )
    }

    // Email verification gate — check via custom header or skip in dev.
    // The header is set by the page server component after Supabase SSR
    // returns the user. In dev / local the header is absent and we let
    // the request through so the developer isn't blocked.
    const emailVerified = request.headers.get('x-email-verified')
    if (emailVerified === 'false') {
      return NextResponse.json(
        { error: { code: 'email_not_verified', message: 'Please verify your email before scanning.' } },
        { status: 403 }
      )
    }
  }

  return NextResponse.next()
}

// Matcher intentionally narrow. Adding /api/* would fire this on every API
// call; if a scan POST ever moves to /api/scan, update this list and the
// pathname check above in the same commit.
export const config = {
  matcher: ['/scan'],
}
