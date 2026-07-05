/**
 * Supabase query functions for scans and findings.
 *
 * All functions in this module are designed for Server Components — they
 * use `createServerSupabaseClient` which reads the auth session from
 * cookies (RLS enforced). Never import this module from a Client Component.
 */

import { createServerSupabaseClient } from './server'

export type ScanRow = {
  id: string
  repo_url: string
  status: string
  created_at: string
  error: string | null
}

export type FindingRow = {
  id: string
  scan_id: string
  severity: string
  title: string
  description: string | null
  file_path: string | null
  line: number | null
  poc_curl: string | null
  remediation_code: string | null
  tier: number
  created_at: string
}

export async function fetchScans(): Promise<ScanRow[]> {
  const supabase = await createServerSupabaseClient()
  const { data, error } = await supabase
    .from('scans')
    .select('id, repo_url, status, created_at, error')
    .order('created_at', { ascending: false })

  if (error) {
    throw new Error(`Failed to fetch scans: ${error.message}`)
  }

  return data ?? []
}

export async function fetchScan(id: string): Promise<ScanRow | null> {
  const supabase = await createServerSupabaseClient()
  const { data, error } = await supabase
    .from('scans')
    .select('id, repo_url, status, created_at, error')
    .eq('id', id)
    .single()

  if (error) {
    if (error.code === 'PGRST116') return null
    throw new Error(`Failed to fetch scan: ${error.message}`)
  }

  return data
}

export async function fetchFindings(scanId: string): Promise<FindingRow[]> {
  const supabase = await createServerSupabaseClient()
  const { data, error } = await supabase
    .from('findings')
    .select('id, scan_id, severity, title, description, file_path, line, poc_curl, remediation_code, tier, created_at')
    .eq('scan_id', scanId)
    .order('created_at', { ascending: true })

  if (error) {
    throw new Error(`Failed to fetch findings: ${error.message}`)
  }

  return data ?? []
}
