/**
 * Server-side Supabase clients: anon (RLS-enforced) + service-role (RLS-bypass).
 *
 * Security boundary:
 *   - `createServerSupabaseClient`  — anon key, RLS enforced, user-scoped.
 *     Use in Server Components, Server Actions, and Route Handlers that act
 *     on behalf of the logged-in user.
 *   - `createServiceClient`         — service-role key, RLS bypassed.
 *     Use ONLY for trusted background work (webhook ingest, scheduled jobs,
 *     admin tooling). Never call from a path that takes user input without
 *     an additional authorization check.
 *   Both must stay server-only. `next/headers` (imported below) throws if
 *   invoked from a Client Component, which is the structural guard against
 *   accidental browser import.
 *
 * Cookie contract (the non-obvious bit):
 *   `@supabase/ssr` uses the `getAll` + `setAll` cookie adapter to mirror the
 *   Supabase auth session into the Next.js cookie jar. A no-op `setAll`
 *   (the previous bug) silently dropped every token refresh, which manifests
 *   as random logouts, repeated refresh calls, and "session expired" errors
 *   on otherwise-valid requests. The try/catch below is the canonical Next.js
 *   App Router pattern: write the cookies when allowed (Route Handlers,
 *   Server Actions), and ignore the failure when called from a Server
 *   Component — middleware is responsible for refreshes in that case.
 *   See: https://supabase.com/docs/guides/auth/server-side
 */

import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'

/**
 * Anon-key server client bound to the current request's cookies.
 *
 * Must be awaited because Next 15's `cookies()` is async.
 */
export async function createServerSupabaseClient() {
  const cookieStore = await cookies()
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => cookieStore.getAll(),
        setAll: (cookiesToSet) => {
          try {
            // Route Handlers + Server Actions can write cookies. Writing in
            // a Server Component throws (read-only cookie store) — caught
            // and ignored because middleware handles refreshes on the next
            // request in that case.
            for (const { name, value, options } of cookiesToSet) {
              cookieStore.set(name, value, options)
            }
          } catch {
            // Called from a Server Component; cookieStore is read-only here.
            // The middleware (see `apps/dashboard/src/middleware.ts`) will
            // pick up the refreshed session on the next request. Safe to
            // ignore — per @supabase/ssr docs, this is the expected fallback.
          }
        },
      },
    },
  )
}

/**
 * Service-role server client. Bypasses RLS; never reads/writes cookies.
 *
 * No `await cookies()` here because the service-role client is intentionally
 * cookie-blind: it has its own JWT, it is not bound to a user session, and
 * giving it a cookie store would invite confusion about which identity a
 * query is acting under.
 */
export function createServiceClient() {
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    {
      cookies: {
        getAll: () => [],
        setAll: () => {
          // No-op by design — see "Cookie contract" in the module doc.
        },
      },
    },
  )
}
