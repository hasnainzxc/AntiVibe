import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

// In-memory store for rate limiting (fallback when no Redis configured)
const rateLimitMap = new Map<string, { count: number; resetAt: number }>()

const WINDOW_MS = 60 * 60 * 1000 // 1 hour
const MAX_REQUESTS = 1 // 1 scan per hour per IP+user

function getRateLimitKey(request: NextRequest): string {
  const ip = request.headers.get('x-forwarded-for')?.split(',')[0]?.trim()
    || request.headers.get('x-real-ip')
    || '127.0.0.1'
  // Combine with user from cookie if available, else IP only
  const userId = request.cookies.get('sb-access-token')?.value?.slice(0, 16) || 'anon'
  return `${ip}:${userId}:scan`
}

function checkRateLimit(key: string): { allowed: boolean; retryAfter?: number } {
  const now = Date.now()
  const entry = rateLimitMap.get(key)

  if (!entry || now > entry.resetAt) {
    rateLimitMap.set(key, { count: 1, resetAt: now + WINDOW_MS })
    return { allowed: true }
  }

  if (entry.count >= MAX_REQUESTS) {
    const retryAfter = Math.ceil((entry.resetAt - now) / 1000)
    return { allowed: false, retryAfter }
  }

  entry.count++
  return { allowed: true }
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  if (pathname === '/scan' && request.method === 'POST') {
    const key = getRateLimitKey(request)
    const { allowed, retryAfter } = checkRateLimit(key)

    if (!allowed) {
      return NextResponse.json(
        { error: { code: 'rate_limited', message: 'Too many scans. Please wait.', retry_after: retryAfter } },
        {
          status: 429,
          headers: {
            'Retry-After': String(retryAfter),
            'X-RateLimit-Limit': String(MAX_REQUESTS),
            'X-RateLimit-Remaining': '0',
          },
        }
      )
    }

    // Email verification gate — check via custom header or skip in dev
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

export const config = {
  matcher: ['/scan'],
}
