# Feature: Shared TypeScript Types

**Purpose:** Zero-runtime-overhead TypeScript types shared across dashboard + Next.js App Server functions + sandbox TypeScript helpers (`packages/shared-types/`).
**Wave:** 1  **Owner task:** 4  **Status:** pending

## Public API
```ts
export type Scan = { id: string; user_id: string; repo_url: string; branch?: string; status: ScanStatus; stack?: Stack; auth_stack?: AuthStack; ... }
export type ScanStatus = 'pending'|'cloning'|'detected'|'tier1_running'|'tier2_running'|'tier3_running'|'normalizing'|'done'|'partial'|'failed';
export type ScanTier = 1|2|3;
export type Stack = 'nextjs'|'express'|'firebase'|'fastapi'|'flask'|'sveltekit';
export type AuthStack = 'nextauth'|'clerk'|'firebase'|'supabase'|'custom';
export type Finding = { id: string; scan_id: string; severity: Severity; title: string; description?: string; file_path?: string; line?: number; evidence_curl?: string; remediation_code?: string; tier: ScanTier; model_source?: 'rule'|'ast'|'llm'|'fuzz'; created_at: string };
export type Severity = 'critical'|'high'|'medium'|'low'|'info';
export type Report = { scan_id: string; markdown: string; json: ScanResult; artifact_url?: string };
export type RouteShape = { path: string; methods: HttpMethod[]; params?: Record<string, ParameterShape>; body_shape?: SchemaShape; auth_required?: boolean };
export type HttpMethod = 'GET'|'POST'|'PUT'|'PATCH'|'DELETE';
export type Tenant = { id: 1|2; name: string };
export type UserRole = 'admin'|'student'|'regular';
export type ForgedToken = { token: string; user_id: string; tenant_id: 1|2; role: UserRole };
export type ScanResult = { scan_id: string; repo_url: string; stack_detected: Stack; auth_stack_detected?: AuthStack; started_at: string; completed_at: string; costs: ScanCosts; tiers: PerTierResults; findings: Finding[] };
export type ScanCosts = { tokens_in: number; tokens_out: number; machine_seconds: number; cents: number };
export type PerTierResults = { '1': { findings: Finding[] }; '2': { spun_up_ms: number; jwt_forged: boolean; routes_extracted: number }; '3': { routes_walked: number; blocked_pivots: number; bola_attempts: number; pocs: PoCCapture[] } };

// Runtime guards for boundary validation
export function assertsScan(x: unknown): asserts x is Scan;
export function assertsFinding(x: unknown): asserts x is Finding;
```

## Internal flow
1. `pnpm-workspace` registers `packages/shared-types`
2. Define all union types as literals matching Metis whitelists (6 stacks, 5 auth stacks, 2 DBs)
3. Add `assertsX` runtime guards using `node:assert` (only for DB boundary reads, never routinely)
4. Export `__fixtures__/` for Vitest smoke tests + downstream consumers

## Inputs
- Metis whitelists from `.omo/drafts/antivibe-saas.md#whitelists-locked`

## Outputs
- `packages/shared-types/dist/index.d.ts` declarations
- `packages/shared-types/dist/index.js` runtime (small consts + asserts)

## Acceptance criteria
- [ ] `pnpm -r build --filter @antivibe/shared-types` exits 0
- [ ] Test: `node -e "console.log(require('@antivibe/shared-types').Severity)"` prints 5 keys
- [ ] Test: `Object.keys(Stack).length` = 6
- [ ] All exports listed `type` keyword (no `interface`)
- [ ] Vitest fixture tests pass typecheck

## Test plan
```
Scenario: Shared-types compiles w/o runtime error
  Steps: node -e "console.log(require('@antivibe/shared-types').Severity)"
  Expected: prints object 5 keys
  Evidence: .omo/evidence/task-4-types-runtime.txt

Scenario: Stack union exhaustively matches Metis whitelist
  Steps: node -e "console.log(Object.keys(require('@antivibe/shared-types').Stack).length)"
  Expected: 6
  Evidence: .omo/evidence/task-4-stack-count.txt
```

## Cross-references
- [see architecture.md#whitelists-locked]
- [see system-design.md#report-schema]
- [see agent-orchestration.md#anti-slop-checklist]

## Changelog
| Date | Change |
|------|--------|
| 2026-07-04 | Initial draft |