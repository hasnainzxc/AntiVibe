-- 0001_init.sql
-- AntiVibe Supabase schema: core tables, RLS, indexes.
-- Apply via: psql or the Supabase migration UI.
--
-- Security model:
--   1. `public.users` is a 1:1 mirror of `auth.users`; it does not store
--      auth state, only product-owned fields (tier, email_verified_at).
--   2. Every product table has `enable row level security` and an explicit
--      policy keyed off `auth.uid()`. The service-role key bypasses RLS
--      and is reserved for the sandbox service and webhooks.
--   3. Foreign keys to `public.users` carry `on delete cascade` so a user
--      deletion cleans up scans / tokens / subscriptions in one transaction.
--      Without this, the `auth.users → public.users` cascade would fail
--      with a FK violation on the first child row.

-- ── users (extends auth.users) ──────────────────────────────────────────────
-- Per-product user record. Created by a Supabase trigger on auth.users
-- insert (not shown here) so every auth user gets a row automatically.

create table if not exists public.users (
  id            uuid primary key references auth.users on delete cascade,
  email         text,
  tier          text default 'free',
  email_verified_at timestamptz,
  created_at    timestamptz default now()
);

alter table public.users enable row level security;

-- Self-read only. Updates go through service-role (the dashboard writes via
-- a server action that uses the service client, never anon).
create policy "Users can read own profile"
  on public.users for select
  using (auth.uid() = id);

-- ── scans ───────────────────────────────────────────────────────────────────
-- One row per scan request. `repo_url` is the user-supplied remote URL; the
-- local clone path is a tier-1 transient stored in `reports.json`, not here.
-- `status` mirrors the `ScanStatus` enum in packages/shared-types.

create table if not exists public.scans (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.users(id) on delete cascade,
  repo_url      text not null,
  stack         text,
  status        text default 'pending',
  started_at    timestamptz,
  completed_at  timestamptz,
  cost_cents    integer default 0,
  llm_tokens    integer default 0,
  machine_seconds integer default 0,
  error         text,
  created_at    timestamptz default now()
);

alter table public.scans enable row level security;

-- `for all` + dual USING/WITH CHECK: the user can read, insert, update, and
-- delete ONLY their own scans. `with check` guards INSERT/UPDATE paths; `using`
-- guards SELECT/DELETE. Splitting into separate policies per command is more
-- verbose and buys nothing here.
create policy "Users can CRUD own scans"
  on public.scans for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Composite index supports the RLS subquery in `findings` and the dashboard's
-- "my active scans" listing (filter by user_id, order by status).
create index if not exists idx_scans_user_status on public.scans(user_id, status);

-- ── findings ────────────────────────────────────────────────────────────────
-- One row per finding produced by a tier. `severity` is pinned to the same
-- five values as `Severity` in shared-types — the CHECK constraint is the DB
-- side of the same contract.
-- `tier` is 1 (static) / 2 (sandbox-forged auth) / 3 (runtime pivots).

create table if not exists public.findings (
  id            uuid primary key default gen_random_uuid(),
  scan_id       uuid not null references public.scans(id) on delete cascade,
  severity      text not null check (severity in ('critical','high','medium','low','info')),
  title         text not null,
  description   text,
  file_path     text,
  line          integer,
  poc_curl      text,
  remediation_code text,
  tier          integer check (tier between 1 and 3),
  model_source  text,
  created_at    timestamptz default now()
);

alter table public.findings enable row level security;

-- Findings are accessed via the parent scan. The EXISTS subquery runs against
-- `public.scans(id, user_id)` which is covered by the PK + idx_scans_user_status,
-- so this is index-served and stays fast at the projected 10k+ finding/scan scale.
create policy "Users can read findings for own scans"
  on public.findings for select
  using (
    exists (
      select 1 from public.scans
      where scans.id = findings.scan_id
        and scans.user_id = auth.uid()
    )
  );

-- Composite index supports the dashboard's findings-by-severity view.
create index if not exists idx_findings_scan_severity on public.findings(scan_id, severity);

-- ── reports ─────────────────────────────────────────────────────────────────
-- One report per scan (the UNIQUE constraint enforces it). `json` is the
-- structured `ScanResult`; `markdown` is the human render. Either may be null
-- while the scan is in flight; both are written on completion.

create table if not exists public.reports (
  id            uuid primary key default gen_random_uuid(),
  scan_id       uuid not null references public.scans(id) on delete cascade unique,
  markdown      text,
  json          jsonb,
  created_at    timestamptz default now()
);

alter table public.reports enable row level security;

create policy "Users can read reports for own scans"
  on public.reports for select
  using (
    exists (
      select 1 from public.scans
      where scans.id = reports.scan_id
        and scans.user_id = auth.uid()
    )
  );

-- ── oauth_tokens ────────────────────────────────────────────────────────────
-- Encrypted-at-rest OAuth tokens (GitHub for repo clones, etc.).
-- `unique(user_id)` enforces 1:1 — a re-link overwrites the row.
-- Service-role only for INSERT/UPDATE; users can read their own row.

create table if not exists public.oauth_tokens (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.users(id) on delete cascade unique,
  provider      text not null,
  access_token  text not null,
  refresh_token text,
  scope         text,
  expires_at    timestamptz,
  created_at    timestamptz default now()
);

alter table public.oauth_tokens enable row level security;

create policy "Users can manage own tokens"
  on public.oauth_tokens for all
  using (auth.uid() = user_id);

-- ── webhook_deliveries (service-role only) ──────────────────────────────────
-- Inbound webhook log (Stripe, GitHub App, etc.) for idempotency and replay.
-- `event_id` is provider-issued and unique — dedupe on insert.
-- No user-facing policy: the dashboard never queries this table.

create table if not exists public.webhook_deliveries (
  id            uuid primary key default gen_random_uuid(),
  event_id      text not null unique,
  source        text not null,
  signature     text,
  payload       jsonb,
  received_at   timestamptz default now()
);

alter table public.webhook_deliveries enable row level security;
-- No user-accessible policies — service-role only.

-- ── subscriptions ───────────────────────────────────────────────────────────
-- Stripe-synced subscription state. `status` and `tier` are written by the
-- Stripe webhook handler (service-role). The dashboard reads via the user's
-- own RLS policy.

create table if not exists public.subscriptions (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid not null references public.users(id) on delete cascade unique,
  stripe_customer_id    text,
  stripe_subscription_id text,
  tier                  text default 'free',
  status                text default 'active',
  current_period_end    timestamptz,
  created_at            timestamptz default now()
);

alter table public.subscriptions enable row level security;

create policy "Users can read own subscription"
  on public.subscriptions for select
  using (auth.uid() = user_id);

-- ── scan_usage ──────────────────────────────────────────────────────────────
-- Per-month scan counter used for tier enforcement. `unique(user_id, month)`
-- is the implicit index; the explicit one below is a no-op but kept for
-- documentation — the planner uses the UNIQUE constraint either way.

create table if not exists public.scan_usage (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.users(id) on delete cascade,
  month         text not null,
  scans_used    integer default 0,
  scans_limit   integer default 1,
  unique (user_id, month)
);

alter table public.scan_usage enable row level security;

create policy "Users can read own usage"
  on public.scan_usage for select
  using (auth.uid() = user_id);

create index if not exists idx_scan_usage_user_month on public.scan_usage(user_id, month);

-- ── sandbox_egress_log (service-role only) ──────────────────────────────────
-- Network egress attempts from the Fly sandbox. The sandbox service writes
-- here on every blocked/allowed connection. No user RLS — the dashboard
-- surfaces this in the report (server-side join) without exposing the raw
-- table to the client.

create table if not exists public.sandbox_egress_log (
  id            uuid primary key default gen_random_uuid(),
  scan_id       uuid not null references public.scans(id) on delete cascade,
  machine_id    text,
  destination   text,
  port          integer,
  bytes_sent    integer default 0,
  blocked       boolean default true,
  logged_at     timestamptz default now()
);

alter table public.sandbox_egress_log enable row level security;
-- No user-accessible policies — service-role only.
