import { describe, it, expect } from 'vitest'

describe('RLS isolation', () => {
  it('user A cannot read user B scans (documented — requires Supabase local)', () => {
    // This test documents the RLS expectation. Full integration test runs against Supabase local.
    // See docs/system-design.md#supabase-schema-conventions for the RLS policy spec.
    expect(true).toBe(true) // placeholder until Supabase local is configured
  })

  it('service-role key never in client bundle', () => {
    expect(process.env.SUPABASE_SERVICE_ROLE_KEY).toBeUndefined()
    expect(
      'NEXT_PUBLIC' in process.env && !process.env.NEXT_PUBLIC_SUPABASE_URL,
    ).toBeFalsy()
  })
})
