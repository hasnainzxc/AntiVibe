import Link from 'next/link'
import { Suspense } from 'react'
import { fetchScans } from '../../../../lib/supabase/scans'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { RetryButton } from './RetryButton'

const statusVariant: Record<string, 'success' | 'destructive' | 'info' | 'warning' | 'secondary'> = {
  done: 'success',
  error: 'destructive',
  pending: 'secondary',
  cloning: 'info',
  scanning: 'info',
  sandboxing: 'info',
  fuzzing: 'info',
  reporting: 'info',
}

function statusColor(status: string) {
  return statusVariant[status] ?? 'secondary'
}

function ScanCard({ scan }: { scan: { id: string; repo_url: string; status: string; created_at: string; error: string | null } }) {
  return (
    <Link href={`/dashboard/scans/${scan.id}`} className="block">
      <Card className="transition-colors hover:bg-muted/50 cursor-pointer">
        <CardHeader>
          <CardTitle className="text-sm font-mono truncate">{scan.repo_url}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <Badge variant={statusColor(scan.status)}>{scan.status}</Badge>
            <span>{new Date(scan.created_at).toLocaleDateString()}</span>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

function ScanListSkeleton() {
  return (
    <div className="grid gap-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <Card key={i}>
          <CardHeader>
            <Skeleton className="h-4 w-3/4" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-3 w-1/3" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

async function ScanList() {
  let scans: { id: string; repo_url: string; status: string; created_at: string; error: string | null }[]
  try {
    scans = await fetchScans()
  } catch {
    return (
      <div className="flex flex-col items-center gap-4 py-16">
        <p className="text-sm text-destructive">Failed to load scans</p>
        <RetryButton />
      </div>
    )
  }

  if (scans.length === 0) {
    return (
      <div className="flex flex-col items-center gap-4 py-16">
        <p className="text-sm text-muted-foreground">No scans yet — paste a GitHub URL to start</p>
      </div>
    )
  }

  return (
    <div className="grid gap-4">
      {scans.map((scan) => (
        <ScanCard key={scan.id} scan={scan} />
      ))}
    </div>
  )
}

export default function ScansPage() {
  return (
    <div className="mx-auto max-w-3xl p-6">
      <h1 className="text-2xl font-bold mb-6">Scans</h1>
      <Suspense fallback={<ScanListSkeleton />}>
        <ScanList />
      </Suspense>
    </div>
  )
}
