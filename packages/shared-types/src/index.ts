// === Scan ===
export type ScanId = string & { readonly __brand: 'ScanId' }

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
export const AuthStack = {
  NEXTAUTH: 'nextauth',
  CLERK: 'clerk',
  FIREBASE: 'firebase',
  SUPABASE: 'supabase',
  CUSTOM: 'custom',
} as const
export type AuthStack = (typeof AuthStack)[keyof typeof AuthStack]

// === Severity ===
export const Severity = {
  CRITICAL: 'critical',
  HIGH: 'high',
  MEDIUM: 'medium',
  LOW: 'low',
  INFO: 'info',
} as const
export type Severity = (typeof Severity)[keyof typeof Severity]

// === Finding ===
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
  tier: 1 | 2 | 3
  model_source?: string
  created_at: string
}

// === Report ===
export type ReportId = string & { readonly __brand: 'ReportId' }

export type Report = {
  id: ReportId
  scan_id: ScanId
  markdown?: string
  json?: ScanResult
  created_at: string
}

// === Route Shape ===
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' | 'HEAD' | 'OPTIONS'

export type RouteShape = {
  path: string
  method: HttpMethod
  params?: string[]
  body_shape?: Record<string, string>
  auth_required: boolean
}

// === Tenant & Auth ===
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
export type Tier1Result = {
  secrets_found: number
  config_flaws: number
  findings: Finding[]
}

export type Tier2Result = {
  stacked_detected: Stack
  auth_stack: AuthStack
  routes_discovered: number
  jwt_forged: boolean
  spun_up_ms: number
}

export type Tier3Result = {
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
export type ApiError = {
  error: {
    code: string
    message: string
    retry_after?: number
  }
}

// === Runtime Guards (boundary validation) ===
export function assertScan(obj: unknown): asserts obj is Scan {
  if (!obj || typeof obj !== 'object') throw new TypeError('not an object')
  const s = obj as Record<string, unknown>
  if (typeof s.id !== 'string') throw new TypeError('Scan.id must be string')
  if (typeof s.repo_url !== 'string') throw new TypeError('Scan.repo_url must be string')
}

export function assertFinding(obj: unknown): asserts obj is Finding {
  if (!obj || typeof obj !== 'object') throw new TypeError('not an object')
  const f = obj as Record<string, unknown>
  if (typeof f.id !== 'string') throw new TypeError('Finding.id must be string')
  if (typeof f.severity !== 'string') throw new TypeError('Finding.severity must be string')
  if (!Object.values(Severity).includes(f.severity as Severity)) throw new TypeError(`invalid severity: ${f.severity}`)
}

export function isSeverity(value: unknown): value is Severity {
  return Object.values(Severity).includes(value as Severity)
}

export function isStack(value: unknown): value is Stack {
  return Object.values(Stack).includes(value as Stack)
}

export function isAuthStack(value: unknown): value is AuthStack {
  return Object.values(AuthStack).includes(value as AuthStack)
}
