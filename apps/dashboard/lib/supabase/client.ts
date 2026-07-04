/**
 * Browser Supabase client factory.
 *
 * Security boundary — anon key only:
 *   Uses the public anon key, which is bound to RLS policies. Every row read
 *   or written through this client is checked against `auth.uid()` on the
 *   server. The anon key is safe to ship to the browser (it is `NEXT_PUBLIC_`
 *   prefixed and embedded in the JS bundle by design).
 *
 * Why `createBrowserClient` (from @supabase/ssr) over `createClient` (from
 *   supabase-js): the SSR-aware variant reads/writes the auth session via
 *   `document.cookie` automatically, so the server-side `createServerSupabaseClient`
 *   sees the same session on the next request. supabase-js alone would store
 *   the session in localStorage and the SSR cookie would not get updated.
 *
 * Usage:
 *   Always construct a new client per component render — do not hoist the
 *   result to module scope. React 19's concurrent rendering can interleave
 *   client reads; a single shared instance is fine for `useEffect` fetches
 *   but not for a render-phase use.
 */

import { createBrowserClient } from '@supabase/ssr'

export function createClient() {
  return createBrowserClient(
    // Both vars are NEXT_PUBLIC_ and ship in the bundle; the non-null
    // assertion is safe because the build fails if they are missing.
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  )
}
