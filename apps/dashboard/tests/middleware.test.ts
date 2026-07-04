import { describe, it, expect, beforeEach } from 'vitest'

// Simulate the rate limiter logic from middleware.ts
// (Unit test of the core algorithm without Next.js runtime)

function createRateLimiter(windowMs = 3600_000, maxRequests = 1) {
  const store = new Map<string, { count: number; resetAt: number }>()

  return {
    check(key: string): { allowed: boolean; retryAfter?: number } {
      const now = Date.now()
      const entry = store.get(key)

      if (!entry || now > entry.resetAt) {
        store.set(key, { count: 1, resetAt: now + windowMs })
        return { allowed: true }
      }

      if (entry.count >= maxRequests) {
        const retryAfter = Math.ceil((entry.resetAt - now) / 1000)
        return { allowed: false, retryAfter }
      }

      entry.count++
      return { allowed: true }
    },
  }
}

describe('Rate limiter', () => {
  let limiter: ReturnType<typeof createRateLimiter>

  beforeEach(() => {
    limiter = createRateLimiter(3600_000, 1)
  })

  it('allows first request', () => {
    const result = limiter.check('user-a:scan')
    expect(result.allowed).toBe(true)
  })

  it('blocks second request within window', () => {
    limiter.check('user-a:scan')
    const result = limiter.check('user-a:scan')
    expect(result.allowed).toBe(false)
    expect(result.retryAfter).toBeGreaterThan(0)
  })

  it('allows different users independently', () => {
    limiter.check('user-a:scan')
    const result = limiter.check('user-b:scan')
    expect(result.allowed).toBe(true)
  })

  it('resets after window expires', async () => {
    // Create limiter with 10ms window for fast reset
    const fastLimiter = createRateLimiter(10, 1)
    fastLimiter.check('user-a:scan')
    // Wait for window to expire
    await new Promise(resolve => setTimeout(resolve, 20))
    const result = fastLimiter.check('user-a:scan')
    expect(result.allowed).toBe(true)
  })
})

describe('Email verification gate', () => {
  function checkEmailVerified(header: string | null): { allowed: boolean; reason?: string } {
    if (header === 'false') {
      return { allowed: false, reason: 'email_not_verified' }
    }
    return { allowed: true }
  }

  it('allows verified email', () => {
    const result = checkEmailVerified('true')
    expect(result.allowed).toBe(true)
  })

  it('blocks unverified email with reason', () => {
    const result = checkEmailVerified('false')
    expect(result.allowed).toBe(false)
    expect(result.reason).toBe('email_not_verified')
  })

  it('allows when header is missing (default allow for dev)', () => {
    const result = checkEmailVerified(null)
    expect(result.allowed).toBe(true)
  })
})
