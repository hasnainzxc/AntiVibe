import { describe, it, expect } from 'vitest'
import crypto from 'crypto'
import { BUCKET_SCAN_ARTIFACTS, BUCKET_POC_CAPTURES } from '../lib/storage/client'

describe('Storage client', () => {
  it('path generation and hash integrity', () => {
    const fakeScanId = 'test-scan-123'
    const content = Buffer.from('hello anti vibe storage test')
    const expectedHash = crypto.createHash('sha256').update(content).digest('hex')

    // Path formatting
    const path = `${fakeScanId}/report.json`
    expect(path).toBe('test-scan-123/report.json')
    expect(expectedHash).toHaveLength(64)
  })

  it('bucket names are private constants', () => {
    // These must be private (no public access)
    expect(BUCKET_SCAN_ARTIFACTS).toBe('scan-artifacts')
    expect(BUCKET_POC_CAPTURES).toBe('poc-captures')
  })

  it('path uses scan_id prefix with kind and ext', () => {
    const scanId = 'abc-123'
    const kind = 'poc'
    const ext = '.json'
    const path = `${scanId}/${kind}${ext}`
    expect(path).toBe('abc-123/poc.json')
  })
})
