# AntiVibe — Billing and Pricing

**Purpose:** Stripe/LemonSqueezy billing plumbing, tier definitions, cost-per-scan unit economics, refund playbook.
**Last Updated:** 2026-07-04
**Owner:** AntiVibe solo-founder

## Plans

| Tier | Price | Limits | Features |
|------|-------|--------|----------|
| Free | $0 | 1 scan/repo per month, email-gated | Static scan only (no Tier 2/3), no auto-PR |
| Indie | $19/month | Unlimited re-scans same repo, up to 5 repos | Full 3-tier + auto-PR (paid repos); no webhook trigger |
| Pro | $49/month | Unlimited repos | Full 3-tier + auto-PR + webhook trigger + private repos + priority queue + email alerts |

Beyond Pro: Team / Enterprise deferred to post-MVP (per "Must NOT Have").

## Cost-per-Scan Math (target unit economics)

### Fly Machine cost
- shared-cpu-1x ≈ $0.00000444/sec (Free tier covers first 3 Machines always)
- Tier 1 scan (static, no sandbox): no Machine → ~$0.00 cost (pure LLM/regex)
- Tier 2+3 scan (full sandbox): avg 8 min runtime × $0.00000444 ≈ **$0.002**
- Worst case (10min circuit cap): $0.027

### LLM token cost
- **Anthropic Claude Sonnet** (structural extractor):
  - $3/1M input tokens, $15/1M output tokens
  - Prompt caching reduces input cost ~90% on repeated context
  - Per scan budget: 50K input cached (~$0.15) + 30K output (~$0.45) = ~**$0.60 worst case**
- **Together AI Llama-3-70B** (fuzzing pattern generator):
  - $0.30/1M input tokens (uncached)
  - Per scan budget: 100K input + 20K output ≈ **$0.06**
- Total LLM per full scan worst case: ~$0.66
- With caching + tuning: ~$0.30

### Total per-scan target
- **$0.30/s**an typical (full 3-tier scan)
- **<$0.50/scan** worst case (Metis guardrail)
- **Break even at**: Indie $19/mo / $0.30 = 63 scans/month per active Indie sub

### Free tier cost
- 1 scan per repo per month
- Average user scans ~2 repos/month at free tier → ~$0.60/user
- Mostly Tier 1 (no sandbox) = ~$0.10/user
- Conversion target: 5% free→paid → covers free-tier subsidy

## Wiring (link Task 38)

```
User subscribes (Stripe Checkout) →
  Stripe webhook `checkout.session.completed` → /api/webhooks/stripe →
  Insert/upsert row in subscriptions(tier='indie'|'pro') +
  Insert webhook_deliveries(event_id) for idempotency →
  Async update scan_usage.scans_limit (free=1, indie=9999, pro=9999)
```

### Lemon Squeezy alternative
- Handles EU VAT automatically (Stripe does too via VAT calculation, but burden on founder)
- Same wiring shape: webhook → upsert → scan_usage update
- Pricing parity: $19/$49 monthly

### Decision (task 38 implementer chooses)
- **Default: Stripe** (more mature + better DX for solo founder in US)
- Switch to Lemon Squeezy if EU customer % >30%

## Subscription Gating Middleware (`middleware.ts` in Next.js)

```ts
// Every /api/scan POST request:
// 1. Auth gate (Supabase JWT)
// 2. Email verify gate (free tier only; paid skip)
// 3. Rate limit gate (1 scan/hour/IP+user — Task 7)
// 4. Tier gate:
//    - free users: scan_usage scans_used < scans_limit (typically 1)
//    - indie/pro users: skip tests usage cap (Per-MVP kindness)
// On access denial, return 403 with `{ error: { code: 'free_tier_exhausted', upgrade_url: '/api/billing/checkout?tier=indie' } }`
```

Metered scanning for indie/pro deferred to post-MVP (flat tier keeps it simple).

## Refund + Chargeback Playbook

| Scenario | Action | Source |
|----------|--------|--------|
| User complains scan stuck (Tier 1 >10min) | Voluntary Stripe refund via dashboard for last invoice + decrement scan_usage.scans_used | `docs/ops-runbook.md#tier-1-scan-stuck` |
| Chargeback filed | Stripe dashboard refuses chargeback w/ scan-logs evidence (machine_seconds + llm_tokens_in) | Stripe dashboard |
| Failed payment (card expired) | Stripe webhook `invoice.payment_failed` → email user → subscription `status=past_due` for 7 days → auto-downgrade to free | Task 38 |
| Mid-month upgrade | Stripe pro-rated (automatic via `proration_behavior='create_prorations'`) | Task 38 |
| Mid-month downgrade | Effective at period end (default Stripe) | Task 38 |
| Disgruntled user wants full refund | Manual refund via Stripe dashboard.WriteLine("do not spam refunds; first contact user via email") | Manual ops |

## Status

| Module | Impl? | Owner Task |
|--------|-------|-----------|
| Stripe products + webhook setup | pending | Task 38 |
| Free tier quota gate | pending | Task 7, 39 |
| Indie + Pro tiers | pending | Task 38 |
| Dashboard billing view | pending | Task 44 |
| Cost tracker (per-scan $ ledger) | pending | Task 40 |
| Circuit-breaker ($0.50 cap) | pending | Task 41 |
| Refund playbook | pending | Manual + Task 41 partial |