'use client'

import { useState, useCallback, useRef } from 'react'
import { ShieldIcon, RadarIcon, GitHubIcon, SettingsIcon, CheckIcon } from '@/components/icons'
import { ScanProgress } from '@/components/scan-progress'
import { FindingCard } from '@/components/finding-card'
import { SeverityCounter } from '@/components/severity-badge'

interface Finding {
  severity: string
  title: string
  file?: string
  line?: number
  description?: string
  code?: string
  poc?: string
  remediation?: string
  cwe?: string
  cvss?: number
}

export default function Home() {
  const [target, setTarget] = useState('')
  const [scanId, setScanId] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [findings, setFindings] = useState<Finding[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [logs, setLogs] = useState<string[]>([])
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
        
        if (data.log) {
          setLogs(prev => [...prev.slice(-10), data.log])
        }

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
    setLogs(['Initializing scan...'])

    try {
      const res = await fetch('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: target.trim() }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || `Server responded with ${res.status}`)
      }

      const data = await res.json()
      setScanId(data.scan_id)
      const s = data.status || 'running'
      setStatus(s)
      setLogs(prev => [...prev, `Scan ID: ${data.scan_id}`])

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

  const severityCounts = findings?.reduce((acc, f) => {
    acc[f.severity] = (acc[f.severity] || 0) + 1
    return acc
  }, {} as Record<string, number>) || {}

  return (
    <div className="flex flex-col min-h-screen bg-av-bg">
      <header className="border-b border-av-border bg-av-surface/50 backdrop-blur-sm sticky top-0 z-50">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <ShieldIcon className="w-6 h-6 text-av-primary" />
            <span className="text-lg font-bold text-av-text-primary">AntiVibe</span>
          </div>
          <div className="flex items-center gap-4">
            <a
              href="https://github.com"
              target="_blank"
              rel="noopener noreferrer"
              className="text-av-text-muted hover:text-av-text-primary transition-colors"
            >
              <GitHubIcon className="w-5 h-5" />
            </a>
            <button className="text-av-text-muted hover:text-av-text-primary transition-colors">
              <SettingsIcon className="w-5 h-5" />
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1 mx-auto w-full max-w-5xl px-6 py-12">
        <div className="mb-12">
          <h1 className="text-4xl font-bold text-av-text-primary mb-3">
            Security Scan
          </h1>
          <p className="text-base text-av-text-secondary max-w-2xl">
            Paste a GitHub URL or local path. Get a triage-ready security report in 90 seconds.
          </p>
        </div>

        <div className="bg-av-surface border border-av-border rounded-lg p-6 mb-8" style={{ boxShadow: '0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2)' }}>
          <form
            onSubmit={(e) => { e.preventDefault(); handleScan() }}
            className="space-y-4"
          >
            <div className="flex gap-3">
              <input
                type="text"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                placeholder="https://github.com/user/repo or /local/path"
                className="flex-1 h-12 px-4 bg-av-bg border border-av-border rounded-md text-sm text-av-text-primary placeholder:text-av-text-muted focus:outline-none focus:border-av-primary transition-colors"
                style={{ fontFamily: 'var(--font-jetbrains-mono)' }}
                disabled={loading}
              />
              <button
                type="submit"
                disabled={loading || !target.trim()}
                className="h-12 px-6 bg-av-primary hover:bg-av-primary-hover disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium rounded-md transition-all duration-150 flex items-center gap-2"
                style={{
                  boxShadow: loading ? '0 0 20px rgba(99,102,241,0.15)' : 'none',
                  transform: loading ? 'scale(1.02)' : 'scale(1)',
                }}
              >
                <RadarIcon className="w-5 h-5" />
                {loading ? 'Scanning...' : 'Scan'}
              </button>
            </div>
            <p className="text-xs text-av-text-muted">
              Next.js • Express • FastAPI • Flask — supported stacks
            </p>
          </form>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">
            {error}
          </div>
        )}

        {loading && status && (
          <div className="mb-8">
            <ScanProgress status={status} logs={logs} />
          </div>
        )}

        {findings && findings.length > 0 && (
          <div className="space-y-6">
            <div className="flex items-center gap-4 flex-wrap">
              <h2 className="text-xl font-semibold text-av-text-primary">
                Findings ({findings.length})
              </h2>
              <div className="flex items-center gap-3 flex-wrap">
                {severityCounts.critical && <SeverityCounter severity="critical" count={severityCounts.critical} />}
                {severityCounts.high && <SeverityCounter severity="high" count={severityCounts.high} />}
                {severityCounts.medium && <SeverityCounter severity="medium" count={severityCounts.medium} />}
                {severityCounts.low && <SeverityCounter severity="low" count={severityCounts.low} />}
              </div>
            </div>
            <div className="space-y-3">
              {findings.map((f, i) => (
                <FindingCard key={i} finding={f} index={i} />
              ))}
            </div>
          </div>
        )}

        {findings && findings.length === 0 && status === 'completed' && (
          <div className="p-6 bg-green-500/10 border border-green-500/30 rounded-lg flex items-center gap-4">
            <div className="w-12 h-12 rounded-full bg-green-500/20 flex items-center justify-center flex-shrink-0">
              <CheckIcon className="w-6 h-6 text-green-500" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-green-400 mb-1">
                No vulnerabilities found
              </h3>
              <p className="text-sm text-av-text-secondary">
                Scan completed clean. No security issues detected.
              </p>
            </div>
          </div>
        )}

        {scanId && !loading && (
          <div className="mt-6 text-xs text-av-text-muted font-mono">
            Scan ID: {scanId}
          </div>
        )}
      </main>

      <footer className="border-t border-av-border bg-av-surface/50 backdrop-blur-sm">
        <div className="mx-auto max-w-5xl px-6 py-6 flex items-center justify-between">
          <p className="text-sm text-av-text-muted">
            AntiVibe — Agentic DevSecOps
          </p>
          <p className="text-xs text-av-text-muted font-mono">
            v0.1.0
          </p>
        </div>
      </footer>
    </div>
  )
}
