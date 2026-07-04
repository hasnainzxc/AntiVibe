/**
 * Shared contract types for AntiVibe (dashboard ↔ sandbox service ↔ Supabase).
 *
 * Import graph:
 *   Imported by every app and every service. Keep this package zero-runtime
 *   (no Node, no DOM, no fetch) so it can be consumed from the edge, the
 *   browser, and Python's transpile pipeline. The runtime guards at the
 *   bottom of the file are the only exception — they are small, tree-shakable,
 *   and intentional: callers need to validate untrusted JSON at trust
 *   boundaries (HTTP, storage) before trusting a value as a `Scan` or
 *   `Finding`.
 *
 * The branded id types (`ScanId`, `FindingId`, `ReportId`) prevent
 * accidentally passing one kind of id where another is expected at the type
 * level. They are erased at runtime — `as ScanId` is the only way to mint one.
 */

// === Scan ===
// Branded id so `scanId` and `userId` can't be swapped silently.
export type ScanId = string & { readonly __brand: 'ScanId' }

// Linear progression of the scan pipeline. The dashboard polls `status` and
// renders the matching step; tier-2/tier-3 also enter these states.
export const ScanStatus = {
  PENDING: 'pending',
  CLONING: 'cloning',
  SCANNING: 'scanning',
  SANDBOXING: 'sandboxing',
  FUZZING: 'fuzzing',
  REPORTING: 'reporting',
  DONE: 'done',
  ERROR: 'error',
} as const
export type ScanStatus = (typeof ScanStatus)[keyof typeof ScanStatus]

// Per-tier status emitted by the Python scanner (`scanner/tier1.py` returns
// `status: "complete" | "partial" | "error"`). Surfaced as a field on each
// tier result so the dashboard can show "tier 1: partial (3 analyzers
// failed)" instead of an opaque blob.
export const TierStatus = {
  COMPLETE: 'complete',
  PARTIAL: 'partial',
  ERROR: 'error',
} as const
export type TierStatus = (typeof TierStatus)[keyof typeof TierStatus]

export type Scan = {
  id: ScanId
  user_id: string
  repo_url: string
  stack?: Stack
  status: ScanStatus
  started_at?: string
  completed_at?: string
  cost_cents: number
  llm_tokens: number
  machine_seconds: number
  error?: string
  created_at: string
}

// === Stacks (locked whitelist — Metis guardrail) ===
// Each value is consumed by `scanner/detect_stack.py` and by the dashboard's
// framework-aware report rendering. Add a new value only in lockstep with
// both — the SQL `scans.stack` column has no CHECK constraint yet, so a
// missing case would silently degrade to the generic report.
export const Stack = {
  NEXTJS: 'nextjs',
  EXPRESS: 'express',
  FIREBASE: 'firebase',
  FASTAPI: 'fastapi',
  FLASK: 'flask',
  SVELTEKIT: 'sveltekit',
} as const
export type Stack = (typeof Stack)[keyof typeof Stack]

// === Auth Stacks (locked whitelist) ===
// Drives tier-2's JWT forge + cookie seeder. Each value maps to a specific
// forge implementation in `sandbox/sandbox/jwt_forge.py`.
export const AuthStack = {
  NEXTAUTH: 'nextauth',
  CLERK: 'clerk',
  FIREBASE: 'firebase',
  SUPABASE: 'supabase',
  CUSTOM: 'custom',
} as const
export type AuthStack = (typeof AuthStack)[keyof typeof AuthStack]

// === Severity ===
// Ordered by remediation urgency. The SQL `findings` table has a CHECK
// constraint pinning the same five values; if you add a value here, add it
// to migrations/0001_init.sql in the same PR.
export const Severity = {
  CRITICAL: 'critical',
  HIGH: 'high',
  MEDIUM: 'medium',
  LOW: 'low',
  INFO: 'info',
} as const
export type Severity = (typeof Severity)[keyof typeof Severity]

// === Finding ===
// One finding per (file, line, rule) triple produced by a tier. `poc_curl` is
// the ready-to-run cURL reproduction the dashboard renders in a copy-paste box.
export type FindingId = string & { readonly __brand: 'FindingId' }

export type Finding = {
  id: FindingId
  scan_id: ScanId
  severity: Severity
  title: string
  description?: string
  file_path?: string
  line?: number
  poc_curl?: string
  remediation_code?: string
  // 1 = static-only, 2 = sandbox-forged auth, 3 = runtime pivot attempts.
  tier: 1 | 2 | 3
  model_source?: string
  created_at: string
}

// === Report ===
// Final aggregated output. `json` is the structured form (programmatic
// consumers), `markdown` is the human-readable render.
export type ReportId = string & { readonly __brand: 'ReportId' }

export type Report = {
  id: ReportId
  scan_id: ScanId
  markdown?: string
  json?: ScanResult
  created_at: string
}

// === Route Shape ===
// Discovered by tier-1's AST parser. `auth_required` is inferred from the
// presence of an auth middleware in the same file (heuristic, not a proof).
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' | 'HEAD' | 'OPTIONS'

export type RouteShape = {
  path: string
  method: HttpMethod
  params?: string[]
  body_shape?: Record<string, string>
  auth_required: boolean
}

// === Tenant & Auth ===
// Admin-only types. `ForgedToken` is a JWT minted by tier-2 to exercise the
// target app's own auth — never the real user session.
export const UserRole = {
  ADMIN: 'admin',
  STUDENT: 'student',
  REGULAR: 'regular',
} as const
export type UserRole = (typeof UserRole)[keyof typeof UserRole]

export type Tenant = {
  id: string
  name: string
  users: ForgedToken[]
}

export type ForgedToken = {
  token: string
  user_id: string
  tenant_id: string
  role: UserRole
}

// === Scan Result (combined tier output) ===
// Assembled by the orchestrator that calls each tier. `duration_ms` on each
// tier is the wall-clock time including any analyzer timeouts; the dashboard
// uses it to render per-tier progress and to bill the user.
export type Tier1Result = {
  status: TierStatus
  duration_ms: number
  secrets_found: number
  config_flaws: number
  findings: Finding[]
}

export type Tier2Result = {
  status: TierStatus
  duration_ms: number
  stacked_detected: Stack
  auth_stack: AuthStack
  routes_discovered: number
  jwt_forged: boolean
  spun_up_ms: number
}

export type Tier3Result = {
  status: TierStatus
  duration_ms: number
  routes_walked: number
  blocked_pivots: number
  bola_attempts: number
  idor_attempts: number
  pocs: Finding[]
}

export type ScanCosts = {
  tokens: number
  machine_seconds: number
  cents: number
}

export type ScanResult = {
  scan_id: ScanId
  // Local clone path produced by tier-1's `clone_repo` — different from
  // `Scan.repo_url`, which is the user-supplied remote URL.
  repo: string
  stack_detected?: Stack
  started_at: string
  completed_at: string
  costs: ScanCosts
  tier1: Tier1Result
  tier2?: Tier2Result
  tier3?: Tier3Result
}

// === Subscription ===
// Mirrored from the `subscriptions` table. `status` is intentionally an
// inline union instead of an enum: it's a Stripe-shaped value, not a
// product-owned one. Add a SubscriptionStatus enum if we ever branch on it.
export const SubscriptionTier = {
  FREE: 'free',
  INDIE: 'indie',
  PRO: 'pro',
} as const
export type SubscriptionTier = (typeof SubscriptionTier)[keyof typeof SubscriptionTier]

export type Subscription = {
  user_id: string
  tier: SubscriptionTier
  status: 'active' | 'canceled' | 'past_due'
  current_period_end?: string
  stripe_customer_id?: string
}

// === API Error Envelope ===
// Wire format for every non-2xx response in the dashboard API. The middleware
// emits `code: 'rate_limited'` and `code: 'email_not_verified'`; the route
// handlers emit `code: 'unauthorized' | 'forbidden' | 'not_found' | 'server_error'`.
// `retry_after` is set when the caller should back off (mirrors the
// `Retry-After` header for clients that only parse the body).
export type ApiErrorCode =
  | 'rate_limited'
  | 'email_not_verified'
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'validation'
  | 'server_error'

export type ApiError = {
  error: {
    code: ApiErrorCode
    message: string
    retry_after?: number
  }
}

// === Runtime Guards (boundary validation) ===
// These throw on shape mismatch. Use them at trust boundaries: when
// receiving JSON from a route handler, when reading a Storage artifact
// that was written by a different tier, or when deserializing a row from
// a SELECT that bypassed TypeScript (e.g. raw RPC).

/** Throws if `obj` is not shaped like a `Scan`. */
export function assertScan(obj: unknown): asserts obj is Scan {
  if (!obj || typeof obj !== 'object') throw new TypeError('not an object')
  const s = obj as Record<string, unknown>
  if (typeof s.id !== 'string') throw new TypeError('Scan.id must be string')
  if (typeof s.repo_url !== 'string') throw new TypeError('Scan.repo_url must be string')
  if (typeof s.user_id !== 'string') throw new TypeError('Scan.user_id must be string')
  if (typeof s.cost_cents !== 'number') throw new TypeError('Scan.cost_cents must be number')
  if (typeof s.llm_tokens !== 'number') throw new TypeError('Scan.llm_tokens must be number')
  if (typeof s.machine_seconds !== 'number') throw new TypeError('Scan.machine_seconds must be number')
  if (typeof s.created_at !== 'string') throw new TypeError('Scan.created_at must be string')
  // `status` is checked against the enum to catch stale wire formats
  // (e.g. `cloning` typo'd as `clone`) that the SQL CHECK constraint would
  // also reject — failing here gives a much clearer stack trace.
  if (!Object.values(ScanStatus).includes(s.status as ScanStatus)) {
    throw new TypeError(`invalid Scan.status: ${String(s.status)}`)
  }
}

/** Throws if `obj` is not shaped like a `Finding`. */
export function assertFinding(obj: unknown): asserts obj is Finding {
  if (!obj || typeof obj !== 'object') throw new TypeError('not an object')
  const f = obj as Record<string, unknown>
  if (typeof f.id !== 'string') throw new TypeError('Finding.id must be string')
  if (typeof f.severity !== 'string') throw new TypeError('Finding.severity must be string')
  if (!Object.values(Severity).includes(f.severity as Severity)) throw new TypeError(`invalid severity: ${f.severity}`)
  if (typeof f.title !== 'string') throw new TypeError('Finding.title must be string')
  if (f.tier !== 1 && f.tier !== 2 && f.tier !== 3) throw new TypeError(`invalid tier: ${String(f.tier)}`)
}

/** Type predicate for boundary parsing — cheap, no throw. */
export function isSeverity(value: unknown): value is Severity {
  return Object.values(Severity).includes(value as Severity)
}

/** Type predicate for the Stack whitelist. */
export function isStack(value: unknown): value is Stack {
  return Object.values(Stack).includes(value as Stack)
}

/** Type predicate for the AuthStack whitelist. */
export function isAuthStack(value: unknown): value is AuthStack {
  return Object.values(AuthStack).includes(value as AuthStack)
}

/** Type predicate for TierStatus (per-tier run outcome). */
export function isTierStatus(value: unknown): value is TierStatus {
  return Object.values(TierStatus).includes(value as TierStatus)
}
