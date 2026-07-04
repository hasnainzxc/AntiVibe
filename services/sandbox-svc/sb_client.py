"""Thin factory for Supabase clients in the sandbox service.

Security boundary — anon vs service-role:
    The anon key is bound to RLS policies: every row read or written is checked
    against `auth.uid()`. Use it for anything that acts on behalf of a logged-in
    user. The service-role key bypasses RLS entirely and is intended for trusted
    background jobs (scan orchestration, billing, scheduled cleanup).

    Concretely:
      - service_role=True  → scanner/sandbox internal use ONLY. Never on a
        request path where the caller is untrusted.
      - service_role=False → user-facing flows (rare in the sandbox service;
        the dashboard is the usual consumer of the anon key, via SSR cookies).

Import graph:
    supabase.create_client — pinned to supabase-py 2.x; the `auth` defaults are
        sufficient because the sandbox service never persists sessions (no
        browser, no cookies).
"""

import os
from supabase import create_client, Client


def get_supabase_client(service_role: bool = False) -> Client:
    """Return a fresh Supabase client.

    Args:
        service_role: When True, use the service-role key (RLS bypass). When
            False, use the anon key (RLS enforced). Defaults to anon.

    Returns:
        A new supabase-py `Client`. The client is not thread-safe across
        long-lived auth state, so callers in concurrent contexts should
        construct one per request — same as `storage._get_service_client`.

    Raises:
        KeyError: if `SUPABASE_URL` is missing, or if `service_role=True` and
            `SUPABASE_SERVICE_ROLE_KEY` is missing. Anon key missing is
            tolerated (returns a client bound to an empty key) so tests can
            stub it without a real env.
    """
    url = os.environ["SUPABASE_URL"]
    key = (
        os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        if service_role
        else os.environ.get("SUPABASE_ANON_KEY", "")
    )
    return create_client(url, key)
