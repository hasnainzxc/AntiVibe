import { Scan, ScanStatus } from '../src/index'

export const validScan: Scan = {
  id: '00000000-0000-0000-0000-000000000001' as Scan['id'],
  user_id: 'user-1',
  repo_url: 'https://github.com/test/repo',
  stack: 'nextjs',
  status: ScanStatus.PENDING,
  cost_cents: 0,
  llm_tokens: 0,
  machine_seconds: 0,
  created_at: new Date().toISOString(),
}
