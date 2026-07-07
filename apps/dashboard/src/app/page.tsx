'use client'

import { useState, useCallback, useRef } from 'react'

export default function Home() {
  const [target, setTarget] = useState('')
  const [scanId, setScanId] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [findings, setFindings] = useState<any[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const pollStatus = useCallback((id: string) => {
    pollingRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/scan?scan_id=${encodeURIComponent(id)}`)
        if (!res.ok) {
          clearInterval(pollingRef.current!)
          setLoading(false)
          setStatus('error')
          setError('Failed to poll scan status')
          return
        }

        const data = await res.json()
        setStatus(data.status)

        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(pollingRef.current!)
          setLoading(false)
          if (data.findings) setFindings(data.findings)
          if (data.error) setError(data.error)
        }
      } catch {
        clearInterval(pollingRef.current!)
        setLoading(false)
        setError('Polling failed')
      }
    }, 2000)
  }, [])

  const handleScan = useCallback(async () => {
    if (!target.trim()) return

    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }

    setLoading(true)
    setError(null)
    setStatus('starting')
    setFindings(null)
    setScanId(null)

    try {
      const res = await fetch('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target: target.trim() }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || `Server responded with ${res.status}`)
      }

      const data = await res.json()
      setScanId(data.scan_id)
      const s = data.status || 'running'
      setStatus(s)

      if (s !== 'completed' && s !== 'failed') {
        pollStatus(data.scan_id)
      } else {
        setLoading(false)
        if (data.findings) setFindings(data.findings)
        if (data.error) setError(data.error)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setError(msg)
      setLoading(false)
    }
  }, [target, pollStatus])

  return (
    <div className="flex flex-col min-h-screen">
      <header className="border-b bg-background">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
          <span className="text-lg font-bold">AntiVibe</span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-3xl px-4 py-12">
        <h1 className="text-2xl font-bold mb-2">Security Scan</h1>
        <p className="text-sm text-muted-foreground mb-6">
          Enter a GitHub URL or local path to scan for vulnerabilities.
        </p>

        <form
          onSubmit={(e) => { e.preventDefault(); handleScan() }}
          className="flex gap-3 mb-6"
        >
          <input
            type="text"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="/tmp/test-repo or https://github.com/user/repo"
            className="flex-1 rounded-lg border border-input bg-background px-4 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <button
            type="submit"
            disabled={loading || !target.trim()}
            className="rounded-lg bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? 'Scanning...' : 'Scan'}
          </button>
        </form>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 mb-4">
            {error}
          </div>
        )}

        {status && !error && status !== 'idle' && (
          <div className="mb-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className={`inline-block size-2 rounded-full ${status === 'completed' ? 'bg-green-500' : status === 'failed' ? 'bg-red-500' : 'bg-yellow-500 animate-pulse'}`} />
              Status: {status}
              {scanId && <span className="text-xs opacity-60">ID: {scanId}</span>}
            </div>
          </div>
        )}

        {findings && findings.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-lg font-semibold">Findings ({findings.length})</h2>
            {findings.map((f, i) => (
              <div key={i} className="rounded-lg border p-4">
                <pre className="text-xs overflow-auto whitespace-pre-wrap">{JSON.stringify(f, null, 2)}</pre>
              </div>
            ))}
          </div>
        )}

        {findings && findings.length === 0 && status === 'completed' && (
          <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
            No findings — scan completed clean.
          </div>
        )}
      </main>
    </div>
  )
}
