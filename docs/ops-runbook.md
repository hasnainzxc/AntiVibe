# AntiVibe — Ops Runbook

**Purpose:** Provisioning, deploy, secrets rotation, incident response, rollback, kill switches.
**Last Updated:** 2026-07-04
**Owner:** AntiVibe solo-founder

## Provisioning (one-time, manual)

### 1. Supabase project
- Create project at `https://supabase.com/dashboard` (region: nearest to Fly.io primary)
- Save `URL`, `anon_key`, `service_role_key` to 1Password / Doppler / Vault
- Apply migrations: `psql "$SUPABASE_DB_URL" -f migrations/0001_init.sql`
- Create storage buckets via dashboard: `scan-artifacts` (private), `poc-captures` (private)

### 2. Fly.io app
- `flyctl apps create antivibe-dashboard` (Next.js)
- `flyctl apps create antivibe-sandbox-svc` (Python FastAPI)
- Set secrets:
  ```
  flyctl secrets set --app antivibe-dashboard \
    SUPABASE_URL=... NEXT_PUBLIC_SUPABASE_URL=... NEXT_PUBLIC_SUPABASE_ANON_KEY=... \
    SUPABASE_SERVICE_ROLE_KEY=... STRIPE_SECRET_KEY=... ...
  flyctl secrets set --app antivibe-sandbox-svc \
    FLY_API_TOKEN=... ANTHROPIC_API_KEY=... TOGETHER_API_KEY=... \
    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...
  ```
- For sandbox Machines created at runtime: a separate Fly "service account" app token needed w/ Machines scope (NOT the user's primary token — least privilege)

### 3. GitHub OAuth App
- Register OAuth App at `https://github.com/settings/developers`
- Name: AntiVibe, Homepage: `https://antivibe.app`, Callback: `https://antivibe.app/api/github/callback`
- Save `client_id` + `client_secret` to secrets
- (Optional upgrade later: GitHub App instead of OAuth App for fine-grained scope + webhook secrets)

### 4. Stripe (or Lemon Squeezy)
- Create Stripe products: `pro_indie_monthly` ($19/mo), `pro_pro_monthly` ($49/mo)
- Configure webhook to `https://antivibe.app/api/webhooks/stripe` w/ events `checkout.session.completed`, `customer.subscription.deleted`, `invoice.payment_failed`
- Save `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET`
- **Lemon Squeezy alt**: preferred for solo founder (handles EU VAT automatically). Pricing parity: $19/$49 monthly, ~5% fee.

### 5. Anthropic + Together/Anyscale accounts
- Anthropic: $100 credit; save `ANTHROPIC_API_KEY`
- Together AI: hosted Llama-3-70B; save `TOGETHER_API_KEY`
- Anyscale backup if Together down

### 6. Upstash Redis
- Create Redis REST instance (free tier for rate limiting)
- Save `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN`

## Daily Deploys

```bash
# Dashboard
cd apps/dashboard && flyctl deploy --image-name antivibe-dashboard:$(git rev-parse --short HEAD)

# Sandbox-svc
cd services/sandbox-svc && flyctl deploy --image-name antivibe-sandbox-svc:$(git rev-parse --short HEAD)

# Migrations
psql "$SUPABASE_DB_URL" -f migrations/NNNN_<new>.sql
```

CI auto-deploys on merge to main; above is manual fallback.

## Secrets + Env Refresh

| Secret | Storage | Rotation Cadence |
|--------|---------|-----------------|
| Supabase service_role key | 1Password / Doppler | Quarterly or on leak |
| Fly API token | Fly dashboard | Yearly |
| Anthropic key | Anthropic console | Yearly or on leak |
| Together key | Together console | Yearly |
| Stripe secret key | Stripe dashboard | Yearly or on leak |
| Stripe webhook secret | Stripe dashboard | On webhook recreating |
| GitHub OAuth client secret | GitHub OAuth app | Yearly or on leak |
| Upstash token | Upstash dashboard | Yearly |

On rotation: update Fly secrets + restart all machines: `flyctl secrets set ... --app ...` then `flyctl apps restart`.

## Incident Response

### Tier 1 scan stuck (>10min)
1. Kill scan in dashboard admin (or directly: `UPDATE scans SET status='failed' WHERE id='...'`)
2. Refund quota: `UPDATE scan_usage SET scans_used = scans_used - 1 WHERE user_id='...' AND month_date='...'`
3. Voluntary Stripe refund via Stripe dashboard if user complains

### Sandbox runaway cost > $0.50/scan
1. **Kill switch**: `bash scripts/kill-machines.sh` — destroys all Fly Machines created in last 1h
2. Disable `POST /api/scan` endpoint temporarily: env toggle `SCANS_DISABLED=true` + redeploy dashboard
3. Investigate via Supabase: `SELECT scan_id, machine_seconds, llm_tokens_in FROM scans WHERE created_at > NOW() - INTERVAL '1 hour' ORDER BY machine_seconds DESC LIMIT 20`
4. Tune circuit-breaker thresholds (Task 41 env `MAX_COST_CENTS`, `MAX_RUNTIME_SECONDS`)

### Anthropic outage (LLM_extractor broken)
1. Env swap to OpenAI: `LLM_PROVIDER=openai`, `OPENAI_API_KEY=<backup>`
2. Redeploy sandbox-svc
3. Cost impact: ~+15% (no prompt caching); document in `docs/system-design.md`

### Together AI outage (LLM_fuzzer broken)
1. Failover to Anyscale: `OSS_INFERENCE_PROVIDER=anyscale`, `ANYSCALE_API_KEY=<backup>`
2. If all OSS hosted down: degrade scan tier Option — skip Tier 3 fuzzing, ship static + sandbox-only report
3. Document the incident in `docs/runbook-incidents/NNNN_<date>.md` w/ postmortem

### Sandbox egress violation detected
1. IMMEDIATELY kill all running scans (`scripts/kill-all-scans.sh`)
2. Investigate Fly audit logs (Fly dashboard > machine > network events)
3. If confirmed leak: rotate all keys (Anthropic/Together/Supabase service role)
4. Send email blast to affected users — full transparency

### GitHub IP rate limit
1. Backoff via env `GITHUB_RATE_LIMIT_BACKOFF=60` (already implemented if Task 35 properly)
2. Defer webhook-triggered scans with `delay_seconds` to avoid staggering

### DB corruption / Supabase outage
1. Toggle `DB_READ_ONLY=true` on dashboard (degrades; returns cached reports)
2. Open Supabase support ticket (priority: paid plan)
3. Restore from last backup (Supabase PITR via `supabase db restore --point-in-time '...'`)

## Rollback

### Fly image
```bash
flyctl image deploy antivibe-dashboard:v<prev> --strategy=canary
```
Tag previous deploys w/ git SHA. Quick rollback = pin to previous image via:
```bash
flyctl config set --image antivibe-dashboard:<prev-sha> --app antivibe-dashboard
flyctl apps restart antivibe-dashboard
```

### Supabase migration
```bash
supabase migration repair --rollback <migration-id>
# or for SQL reversions:
psql "$SUPABASE_DB_URL" -f migrations/<NNNN>_down.sql
```

## Runbooks for common failures

### Sandbox hangs (Machine boots but app never ready)
1. Check `flyctl logs --app antivibe-sandbox-svc --instance <machine_id>` for boot errors
2. If image pull > 30s cold start noted → bump to `shared-cpu-2x` or pre-warm pool
3. If app stuck in `npm install` → check postinstall block guard still applied (see task 9)

### Egress violation via logs (outbound curl to external API recorded)
1. Review `webhook_deliveries` audit log for the offending scan_id
2. Snapshot Machine logs + audit trail → save to `.omo/incidents/<date>-egress-leak.json`
3. Patch egress rule (likely iptables misconfig in `/services/sandbox-svc/fly/network_rules.py`)
4. Per Metis fail-closed: if rule patch doesn't apply on scan start, scan fails fast

### Auto-PR mis-fire (opened PR on wrong repo)
1. Rollback: `gh pr close <number> --repo <repo>` + `gh branch delete antivibe/fix-...` 
2. Audit `webhook_deliveries` to see if user authorized wrong repo
3. Add a repo-allowlist UI toggle in dashboard (future feature)

## Status

| Runbook section | Impl? | Owner Task |
|----------------|-------|-----------|
| Provisioning list | done (this doc) | N/A |
| Daily deploys | pending | Task 1 (CI), GH Actions workflow |
| Secrets rotation | done (this doc) | Manual ops process |
| Incident: Tier 1 stuck | pending | Task 41 (circuit-breaker) |
| Incident: runaway cost | pending | Task 40 (cost tracker), Task 50 (hardening) |
| Incident: LLM outage | pending | Task 14, 27 |
| Egress violation | pending | Task 18, 50 |
| DB rollback | done (documented) | Supabase ops |
| Kill switches script | pending | Task 50 |