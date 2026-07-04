import { createClient } from '@supabase/supabase-js'

const BUCKET_SCAN_ARTIFACTS = 'scan-artifacts'
const BUCKET_POC_CAPTURES = 'poc-captures'

function getServiceClient() {
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { auth: { autoRefreshToken: false, persistSession: false } }
  )
}

export async function uploadScanArtifact(
  scanId: string,
  kind: string,
  content: Buffer | string,
  bucket: string = BUCKET_SCAN_ARTIFACTS
): Promise<string> {
  const client = getServiceClient()
  const ext = kind.includes('.') ? '' : '.json'
  const path = `${scanId}/${kind}${ext}`
  const { error } = await client.storage.from(bucket).upload(path, content, { upsert: true })
  if (error) throw new Error(`Storage upload failed: ${error.message}`)
  return path
}

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
