# Feature: Sandbox Spin-up

**Purpose:** Fly Machine creation + egress DENY-ALL rule application + auto-destroy + audit log to Supabase.
**Wave:** 3  **Owner task:** 18  **Status:** pending

## Public API
```python
@dataclass
class SandboxHandle:
    machine_id: str
    sandbox_url: str  # http://<machine>.fly.dev:3000 or similar
    seed_credentials: dict  # user_A/user_B w/ tokens

class SandboxSpinup:
    def __init__(self, *, fly_client: FlyClient, sb_client, seeder: MockDBSeeder): ...
    async def run(self, *, scan_id: str, repo_root: Path, stack: Stack, image_ref: str) -> SandboxHandle: ...
```

## Internal flow
1. Generate Dockerfile via AppContainerizer (Task 16)
2. Call `fly_client.create_machine(image=image_ref, ram_mb=512, disk_gb=1)`
3. Apply egress rules via `network_rules.py` (DENY ALL outbound except localhost): iptables rewrite at boot
4. Pre-seed DB via MockDBSeeder (Task 17) — executes a sidecar container w/ Postgres OR Firebase emulator by `docker exec` inside Machine
5. Inject `.env` rewrite into app-under-test pointing at localhost DB
6. Wait for app-under-test to boot (curl localhost port via `flyctl ssh` proxy)
7. Subscribe to outbound attempt log channel → log every egress event to `public.sandbox_egress_log` via parent sandbox-svc
8. Register `atexit` to destroy Machine on parent crash

## Inputs
- scan_id, repo_root, stack, image_ref

## Outputs
- SandboxHandle (machine_id, sandbox_url, seed_credentials dict)
- Structlog spans `machine.create.requested` → `machine.boot.ready`

## Acceptance criteria
- [ ] Fly Machine boots < 30s cold (< 2s hot)
- [ ] Egress rule applied at boot; egress test suite confirms ALL outbound blocked except localhost
- [ ] Machine destroyed on scan completion OR crash (verified via Fly API)
- [ ] All egress attempts logged to `sandbox_egress_log` table (BLOCKED action should be every row)

## Test plan
```
Scenario: Machine boots + app responds
  Steps: spinup fixture nextjs-firebase-vuln
  Expected: sandbox_url returns 200 on /
Scenario: Egress DENY ALL enforced
  Steps: ssh into machine; curl https://example.com
  Expected: blocked by iptables rule; logged row in sandbox_egress_log w/ action=blocked
Scenario: Auto-destroy on exit
  Steps: trigger scan exit; list active machines
  Expected: 0 active machines for the scan's app
```

## Cross-references
- [see sandbox-isolation.md#egress-policy]
- [see security-threat-model.md#info-disclosure]
- [see ops-runbook.md#egress-violation-via-logs]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |