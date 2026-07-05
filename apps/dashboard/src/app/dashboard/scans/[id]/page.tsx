import Link from 'next/link'
import { notFound } from 'next/navigation'
import { Suspense } from 'react'
import { fetchScan, fetchFindings } from '../../../../../lib/supabase/scans'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { PoCToggle } from './PoCToggle'
import { RetryButton } from './RetryButton'

const severityVariant: Record<string, 'destructive' | 'warning' | 'info' | 'secondary'> = {
  critical: 'destructive',
  high: 'warning',
  medium: 'info',
  low: 'secondary',
}

const statusVariant: Record<string, 'success' | 'destructive' | 'info' | 'secondary'> = {
  done: 'success',
  error: 'destructive',
  pending: 'secondary',
  cloning: 'info',
  scanning: 'info',
  sandboxing: 'info',
  fuzzing: 'info',
  reporting: 'info',
}

function severityColor(severity: string) {
  return severityVariant[severity] ?? 'secondary'
}

function statusColor(status: string) {
  return statusVariant[status] ?? 'secondary'
}

function FindingCard({ finding }: { finding: {
  id: string
  severity: string
  title: string
  description: string | null
  file_path: string | null
  line: number | null
  poc_curl: string | null
  remediation_code: string | null
  tier: number
}}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Badge variant={severityColor(finding.severity)}>{finding.severity}</Badge>
          <CardTitle className="text-sm">{finding.title}</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {finding.description && (
          <p className="text-sm text-muted-foreground">{finding.description}</p>
        )}
        {(finding.file_path || finding.line) && (
          <p className="text-xs font-mono text-muted-foreground">
            {finding.file_path}{finding.line ? `:${finding.line}` : ''}
          </p>
        )}
        {finding.remediation_code && (
          <pre className="rounded-md bg-muted p-3 text-xs overflow-x-auto">{finding.remediation_code}</pre>
        )}
        {finding.poc_curl && <PoCToggle poc={finding.poc_curl} />}
      </CardContent>
    </Card>
  )
}

function FindingSkeleton() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <Card key={i}>
          <CardHeader>
            <Skeleton className="h-4 w-1/2" />
          </CardHeader>
          <CardContent className="space-y-2">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-2/3" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

async function ScanDetail({ id }: { id: string }) {
  let scan: { id: string; repo_url: string; status: string; created_at: string; error: string | null } | null
  try {
    scan = await fetchScan(id)
  } catch {
    return (
      <div className="flex flex-col items-center gap-4 py-16">
        <p className="text-sm text-destructive">Failed to load scan details</p>
        <RetryButton />
      </div>
    )
  }
  if (!scan) notFound()

  let findings: { id: string; scan_id: string; severity: string; title: string; description: string | null; file_path: string | null; line: number | null; poc_curl: string | null; remediation_code: string | null; tier: number; created_at: string }[]
  try {
    findings = await fetchFindings(id)
  } catch {
    return (
      <div className="flex flex-col items-center gap-4 py-16">
        <p className="text-sm text-destructive">Failed to load findings</p>
        <RetryButton />
      </div>
    )
  }

  return (
    <>
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="font-mono text-sm truncate">{scan.repo_url}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <Badge variant={statusColor(scan.status)}>{scan.status}</Badge>
            <span>{new Date(scan.created_at).toLocaleDateString()}</span>
            <span>{findings.length} finding{findings.length !== 1 ? 's' : ''}</span>
          </div>
        </CardContent>
      </Card>

      {findings.length === 0 ? (
        <div className="flex flex-col items-center gap-4 py-16">
          <p className="text-sm text-muted-foreground">No vulnerabilities found — great job!</p>
        </div>
      ) : (
        <div className="space-y-4">
          {findings.map((f) => (
            <FindingCard key={f.id} finding={f} />
          ))}
        </div>
      )}
    </>
  )
}

export default async function ScanDetailPage(props: { params: Promise<{ id: string }> }) {
  const { id } = await props.params

  return (
    <div className="mx-auto max-w-3xl p-6">
      <Link href="/dashboard/scans" className="text-sm text-muted-foreground hover:text-foreground mb-4 inline-block">
        &larr; Back to scans
      </Link>
      <Suspense fallback={<FindingSkeleton />}>
        <ScanDetail id={id} />
      </Suspense>
    </div>
  )
}
