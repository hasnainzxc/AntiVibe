/**
 * Server-only Supabase Storage client for scan artifacts and PoC captures.
 *
 * Security boundary:
 *   Uses the service-role key, which bypasses RLS. This module therefore must
 *   never be imported from a Client Component, an Edge-runtime Route Handler,
 *   or any code path reachable from the browser. The
 *   'apps/dashboard/src/lib/storage' re-export path (if added later) is
 *   forbidden; keep callers in app Route Handlers and Server Components only.
 *
 * Why createClient (supabase-js) instead of createServerClient (ssr):
 *   These helpers do not touch cookies or session state — they only sign
 *   storage requests. The lower-level supabase-js client is sufficient and
 *   avoids pulling in the @supabase/ssr cookie adapter. The auth options
 *   below disable token refresh / persistence explicitly: there is no user
 *   session to refresh, and a stray in-memory token would be a footgun.
 *
 * Path convention:
 *   scanId/kind with the same extension rules as the Python storage module.
 *   Mirrors 'storage.upload_scan_artifact' in services/sandbox-svc/storage.
 *   Do not change one without the other.
 */

import { createClient } from '@supabase/supabase-js'

const BUCKET_SCAN_ARTIFACTS = 'scan-artifacts'
const BUCKET_POC_CAPTURES = 'poc-captures'

/** Build a fresh storage client. New client per call keeps token rotation effective. */
function getServiceClient() {
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    // Disable refresh + persistence: this client is stateless from an auth
    // perspective. Without these flags, supabase-js would attempt to refresh
    // anon tokens via the persisted session, which doesn't exist for the
    // service-role flow.
    { auth: { autoRefreshToken: false, persistSession: false } }
  )
}

/**
 * Upload a scan artifact (report, PoC transcript, raw finding dump…).
 *
 * 'upsert: true' so re-running a scan replaces the previous artifact instead
 * of leaving orphans — same contract as the Python storage module.
 *
 * @returns the storage path ('{scanId}/{kind}{ext}').
 * @throws Error on supabase-js surfaced error.
 */
export async function uploadScanArtifact(
  scanId: string,
  kind: string,
  content: Buffer | string,
  bucket: string = BUCKET_SCAN_ARTIFACTS
): Promise<string> {
  const client = getServiceClient()
  // `.includes('.')` mirrors the Python `ext = "" if "." in kind else ".json"`
  // rule: a logical name like `report` gets `.json`, a fully-qualified
  // filename like `capture.bin` is kept as-is.
  const ext = kind.includes('.') ? '' : '.json'
  const path = `${scanId}/${kind}${ext}`
  const { error } = await client.storage.from(bucket).upload(path, content, { upsert: true })
  if (error) throw new Error(`Storage upload failed: ${error.message}`)
  return path
}

/**
 * Download an artifact and return it as a Node Buffer.
 *
 * Returns Buffer (not Uint8Array) so callers can feed it straight into
 * `JSON.parse(buffer.toString('utf8'))` or `crypto.createHash('sha256')`.
 *
 * @throws Error on missing object, RLS denial (shouldn't fire — service-role
 *         bypasses RLS), or transport failure.
 */
export async function getScanArtifact(
  scanId: string,
  kind: string,
  bucket: string = BUCKET_SCAN_ARTIFACTS
): Promise<Buffer> {
  const client = getServiceClient()
  const ext = kind.includes('.') ? '' : '.json'
  const path = `${scanId}/${kind}${ext}`
  const { data, error } = await client.storage.from(bucket).download(path)
  if (error) throw new Error(`Storage download failed: ${error.message}`)
  return Buffer.from(await data.arrayBuffer())
}

/**
 * Delete every artifact under '{scanId}/'.
 *
 * No-op when the folder is empty. Used by the scan-cancel handler and the
 * TTL cleanup cron. Throws on transport error — caller should log and
 * continue; storage orphans are bounded by the bucket lifecycle policy.
 */
export async function deleteScanArtifacts(scanId: string, bucket: string = BUCKET_SCAN_ARTIFACTS): Promise<void> {
  const client = getServiceClient()
  const { data: files, error: listErr } = await client.storage.from(bucket).list(scanId)
  if (listErr) throw new Error(`Storage list failed: ${listErr.message}`)
  if (files && files.length > 0) {
    const paths = files.map((f) => `${scanId}/${f.name}`)
    const { error } = await client.storage.from(bucket).remove(paths)
    if (error) throw new Error(`Storage delete failed: ${error.message}`)
  }
}

export { BUCKET_SCAN_ARTIFACTS, BUCKET_POC_CAPTURES }
