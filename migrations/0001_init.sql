-- 0001_init.sql
-- AntiVibe Supabase schema: core tables, RLS, indexes
-- Apply via: psql or Supabase migration UI

-- ── users (extends auth.users) ──────────────────────────────────────────────

create table if not exists public.users (
  id            uuid primary key references auth.users on delete cascade,
  email         text,
  tier          text default 'free',
  email_verified_at timestamptz,
  created_at    timestamptz default now()
);

alter table public.users enable row level security;

create policy "Users can read own profile"
  on public.users for select
  using (auth.uid() = id);

-- ── scans ───────────────────────────────────────────────────────────────────

create table if not exists public.scans (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.users(id),
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

create policy "Users can CRUD own scans"
  on public.scans for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create index if not exists idx_scans_user_status on public.scans(user_id, status);

-- ── findings ────────────────────────────────────────────────────────────────

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

create policy "Users can read findings for own scans"
  on public.findings for select
  using (
    exists (
      select 1 from public.scans
      where scans.id = findings.scan_id
        and scans.user_id = auth.uid()
    )
  );

create index if not exists idx_findings_scan_severity on public.findings(scan_id, severity);

-- ── reports ─────────────────────────────────────────────────────────────────

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

create table if not exists public.oauth_tokens (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.users(id) unique,
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

create table if not exists public.webhook_deliveries (
  id            uuid primary key default gen_random_uuid(),
  event_id      text not null unique,
  source        text not null,
  signature     text,
  payload       jsonb,
  received_at   timestamptz default now()
);

alter table public.webhook_deliveries enable row level security;
-- No user-accessible policies — service-role only

-- ── subscriptions ───────────────────────────────────────────────────────────

create table if not exists public.subscriptions (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid not null references public.users(id) unique,
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

create table if not exists public.scan_usage (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.users(id),
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
-- No user-accessible policies — service-role only
