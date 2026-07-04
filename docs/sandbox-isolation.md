# AntiVibe — Sandbox Isolation Spec

**Purpose:** Fly Machine sandbox specs + egress policy + DB mocking + JWT forge partner policy + cleanup routine + fail-closed response.
**Last Updated:** 2026-07-04
**Owner:** AntiVibe solo-founder

## Machine Specs

| Property | Value | Reason |
|----------|-------|--------|
| Machine type | `shared-cpu-1x` | Free-tier-friendly; isolated scale via auto-destroy |
| RAM | 512MB | Sufficient for typical vibe-coded app boot (no ML models onboard) |
| Disk | 1GB ephemeral | App + node_modules/<python> deps + shallow repo clone |
| Region | Random (Fly picks nearest idle) | Heat distribution; less ABUSE pattern |
| Lifecycle TTL | 60 seconds idle (auto-destroy by Fly) | Defense-in-depth in case destroy hook misses |
| Boot time target | <2s hot image / <30s cold image | Metis p95 <15min total scan budget; cold start eats 30s = OK if once |
| Pre-warm pool | 3 Machines per supported stack at peak times | Mitigate cold (compare Task 21) |
| Network | Default DENY-ALL outbound; allow localhost only | Metis guardrail: egress DENY ALL |

## Egress Policy

At Fly firewall level (via `fly.toml` w/ `experimental.network=true` rewrite, or via iptables inside Machine):

```python
# services/sandbox-svc/fly/network_rules.py
DENY_ALL_OUTBOUND = True
ALLOWED_OUTBOUND = [
    {"destination": "127.0.0.1/32", "port": "*"},  # localhost ONLY
]

# Every other outbound attempt is logged BEFORE firewall drop
iptables -A OUTPUT -d ! 127.0.0.1/32 -j LOG --log-prefix "AV_EGRESS_BLOCKED "
iptables -A OUTPUT -d ! 127.0.0.1/32 -j DROP
```

**Forbidden destinations**:
- External APIs (the app-under-test calling its real Supabase/Firebase/etc)
- GitHub API
- LLM providers (Anthropic, Together) — these call from `sandbox-svc` (parent), never from inside the sandbox
- Hacker-controlled IP (fingerprinting probe)

**Permitted destinations**:
- Localhost (intra-Machine, app-under-test calling its own mock DB on localhost:5432)
- That's it.

**Audit log**: every outbound attempt logged BEFORE drop. Saved to `public.sandbox_egress_log` table via parent autonomous call (sandbox-svc subscribes to machine logs):

```
{ "scan_id": "...", "machine_id": "...", "attempted_at": "ISO", "destination": "1.2.3.4", "port": 443, "action": "blocked" }
```

**Fail-closed**: if `network_rules.py` fails to apply on Machine boot, scan aborts immediately + scan marked `failed` w/ error `egress_rule_apply_failed`. User refunded quota. Alert fires to solo founder on >3 failures/hour.

## Repo Clone Guardrails (link to Task 9 spec)

| Guard | Enforcement | Source |
|-------|-------------|--------|
| Shallow clone | `git clone --depth 1` | Metis |
| No LFS | `GIT_LFS_SKIP_SMUDGE=1` | Metis |
| Size cap 500MB | Pre-clone `git ls-remote --heads` + size estimate; reject >500MB | Metis |
| No recursive submodules | `--recurse-submodules` NOT passed | Metis |
| Postinstall block | `npm install --ignore-scripts=true` (via rewritten `.npmrc`); `PIP_NO_BUILD_ISOLATION=0` (kept) | Metis |
| No Git-thought-injection | Clone commits specific SHA only (pin after `ls-remote`) | `docs/security-threat-model.md#clond-vs-real-repo-drift` |

## DB Mocks

### Postgres (supports all stacks indirectly)
- Ephemeral pg container (🐘 pgvector/pgvector:pg16 image is fine; no vector support needed but smaller) inside same Fly Machine
- Port: `localhost:5432`
- Schema: minimal — 2 tenants × 5 users each (10 total)
- Seeded by `mock_db_seeder.py` (Task 17):
  - `users` table: 10 users w/ fake emails + `tenant_id` + `role` (admin/student/regular)
  - `posts` table: 5 posts per user (50 total) — content w/ fake password_hash field for BOLA testing
  - `settings` table: 1 row per user (10 total)
  - `admins` table: 5 admin rows w/ `password_hash` field w/ fake bcrypt strings
  - `universities` table: 2 fake "universities" (tenant 1: "University A", tenant 2: "University B") w/ admin email + password_hash
  - Config file in cloned repo: rewrite `.env` to point at `localhost:5432` w/ fake creds

### Firestore (supports Firebase stack)
- Firebase emulators container (`ghcr.io/firebase/firebase-emulator:latest`) inside same Machine
- Port: `localhost:8080` (Firestore emulator) + `localhost:9099` (Auth emulator)
- Seeded via `firebase-admin` Python client:
  - Pre-seed 10 fake users via `Auth Emulator REST: POST /identitytoolkit.googleapis.com/v1/accounts:signUp`
  - Pre-seed 2 collections:
    - `UserData/{uid}` w/ `password`, `password_hash`, `admin_email`, `university_id` (cross-tenant test)
    - `Universities/{univ_id}` w/ `name`, `admin_uid`, `password_hash`
  - `firestore.rules` from cloned repo applied to emulator (Task 13 may detect that's open)
- JWT forge: use emulator's `createSessionCookie(uid)` for User_A and User_B

### AntiVibe injects its own DB mocks
- Mock connection string injected via `.env` rewrite in clone:
  - `DATABASE_URL=postgresql://antivibe:antivibe@localhost:5432/antivibe` (for Postgres stacks)
  - `FIREBASE_AUTH_EMULATOR_HOST=localhost:9099`, `FIRESTORE_EMULATOR_HOST=localhost:8080`
- Real API keys in `.env` are STRIPPED (per LLM sanitizer + clone guard)

## JWT Forge

See `docs/system-design.md#jwt-forge-spec` for the 5 forge adapters (NextAuth, Clerk, Firebase, Supabase, custom).

Two dummy users per scan:
- **User_A**: tenant_id=1, role=student, email=`a@antivibe.test`, password=`student-1`
- **User_B**: tenant_id=2, role=admin, email=`b@antivibe.test`, password=`admin-2`

Tokens include `tenant_id` claim for cross-tenant BOLA tests.

## Cleanup

- **Destroy on completion**: `fly_client.destroy_machine(machine_id)` called by Tier 3 orchestrator on `exhausted_avenues | cost_cap | circuit_breaker`
- **TTL safety net**: Machine auto-destroys after 60s idle (set at create)
- **atexit handler**: sandbox-svc registers `atexit.register(destroy_machine)` for parent process crashes
- **Image not committed after scan** — Fly Machines don't snapshot by default in this use
- **Audit log**: every Machine create/destroy logged to Supabase `scans.stage` JSONB column w/ `machine.created`/`machine.destroyed` events

## Audit Log

Per Machine lifecycle, following events emitted via `structlog` to Supabase:
- `machine.create.requested` (scan_id, image, region)
- `machine.create.completed` (machine_id, duration_ms)
- `machine.boot.ready` (verified via health-check endpoint)
- `machine.egress.attempt` (blocked)
- `machine.tier3.start` / `machine.tier3.done`
- `machine.destroy.requested` / `machine.destroy.completed`

## Failure Modes + Responses

| Failure | Detection | Response |
|---------|-----------|----------|
| Machine fails to boot (>120s) | `wait_for_running` timeout | Mark scan `status=failed`, error=`machine_boot_timeout`, refund quota |
| App-under-test OOM (RAM >512MB) | Machine exit code 137 | Mark scan `failed`, error=`oom`, cap exceeded → upgrade Machine size |
| Network partition (Machine can't reach audit log) | heartbeat loss >30s | Kill Machine via Fly API; mark `failed`, error=`heartbeat_lost` |
| Concurrent Fly quota exceeded (10 scans parallel) | Fly API 429 response | Queue scan w/ `status=pending`; retry after delay |
| Cold start >30s (image pull slow) | Boot timer | Pre-warm pool: increment to 5 Machines per stack at peak hours |
| Egress rule fails to apply | Boot-time assertion | Fail-closed: abort scan, error=`egress_rule_apply_failed`, refund quota + alert solo founder if >3/hour |

## Status

| Subsystem | Impl? | Owner Task |
|-----------|-------|-----------|
| Fly Machines client | pending | Task 5 |
| Machine specs config | done (this doc) | N/A |
| Egress DENY ALL rule | pending | Task 18 |
| Egress audit log table | pending | Task 18 (DDL added in Task 3) |
| Mock Postgres seeder | pending | Task 17 |
| Firestore emulator seeder | pending | Task 17 |
| JWT forge adapters | pending | Task 20 (5 adapters) |
| Auto-destroy + atexit | pending | Task 5, 18 |
| Boot health probe | pending | Task 21 |
| Pre-warm pool | pending v1.1 | Future after Task 21 |
| Fail-closed abort | pending | Task 18 |