'use client'

import { Shield, FileCheck, AlertTriangle, AlertCircle, Info, ChevronRight, Terminal, Loader2 } from 'lucide-react'
import { FindingCard } from './finding-card'
import Image from 'next/image'

const STAGES = [
  { key: 'queued', label: 'Queued', icon: Loader2 },
  { key: 'cloning', label: 'Cloning', icon: ChevronRight },
  { key: 'tier1', label: 'Static Analysis', icon: Shield },
  { key: 'tier2', label: 'Sandbox + Fuzz', icon: AlertTriangle },
  { key: 'completed', label: 'Completed', icon: FileCheck },
]

const STAGE_LOGS: Record<string, string[]> = {
  queued: ['Connecting to scan orchestrator...', 'Allocating sandbox resources...', 'Queue position: 1'],
  cloning: ['Cloning repository...', 'Checking out shallow clone (--depth 1)...', 'Indexing file tree...', 'Detecting framework & stack...'],
  tier1: ['Running AST parsers...', 'Scanning for hardcoded secrets...', 'Entropy analysis on strings...', 'LLM semantic review of configs...', 'Checking security headers...'],
  tier2: ['Spinning up Fly Machine microVM...', 'Seeding mock database...', 'Forging JWT tokens for dummy tenants...', 'Building route index...', 'Running Strix fuzz agent...', 'Probing endpoints for BOLA/IDOR...'],
  completed: ['Aggregating findings...', 'Triaging severity levels...', 'Generating remediation patches...', 'Scan complete.'],
}

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info']

function getStageIndex(status: string | null): number {
  if (!status) return -1
  if (status === 'failed') return STAGES.length - 1
  const idx = STAGES.findIndex((s) => s.key === status)
  return idx >= 0 ? idx : -1
}

function severityColor(sev: string): string {
  switch (sev) {
    case 'critical': return 'bg-red-500'
    case 'high': return 'bg-orange-500'
    case 'medium': return 'bg-yellow-500'
    case 'low': return 'bg-blue-500'
    default: return 'bg-gray-400'
  }
}

interface ScanTrackerProps {
  target: string
  scanId: string | null
  status: string | null
  findings: any[] | null
  error: string | null
  loading: boolean
}

export function ScanTracker({ target, scanId, status, findings, error, loading }: ScanTrackerProps) {
  const stageIdx = getStageIndex(status)
  const isFailed = status === 'failed'
  const isCompleted = status === 'completed'
  const hasActiveScan = loading || (scanId && !isCompleted && !isFailed)

  // Sort findings by severity
  const sortedFindings = findings
    ? [...findings].sort((a, b) => {
        const ai = SEVERITY_ORDER.indexOf(a.severity?.toLowerCase() ?? 'info')
        const bi = SEVERITY_ORDER.indexOf(b.severity?.toLowerCase() ?? 'info')
        return ai - bi
      })
    : null

  // Severity summary counts
  const severityCounts = sortedFindings
    ? sortedFindings.reduce((acc, f) => {
        const s = f.severity?.toLowerCase() ?? 'info'
        acc[s] = (acc[s] || 0) + 1
        return acc
      }, {} as Record<string, number>)
    : {}

  if (!hasActiveScan && !isCompleted && !isFailed && !findings) {
    return (
      <div className="max-w-[720px] mx-auto px-6 mt-12">
        <div className="rounded-2xl bg-white border border-[#e7e6f4] p-8 text-center">
          <div className="w-16 h-16 rounded-2xl bg-[#f1f2f9] flex items-center justify-center mx-auto mb-4">
            <Image src="/illustrations/sandbox.png" alt="" width={48} height={48} className="w-12 h-12 object-contain opacity-60" />
          </div>
          <h3 className="font-display text-[20px] font-medium text-[#281950] mb-2">Ready to scan</h3>
          <p className="font-body text-[14px] text-[#5e537c] max-w-[320px] mx-auto">
            Paste a repo URL above and hit <strong className="text-[#7c3aed]">Scan your repo</strong> to start an audit.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-[900px] mx-auto px-6 mt-10">
      {/* ── Scan Header ── */}
      <div className="rounded-2xl bg-white border border-[#e7e6f4] overflow-hidden">
        {/* Target + ID bar */}
        <div className="px-6 py-4 border-b border-[#e7e6f4] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div className="flex items-center gap-3 min-w-0">
            <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${isFailed ? 'bg-red-500' : isCompleted ? 'bg-green-500' : 'bg-amber-400 animate-pulse'}`} />
            <span className="font-body text-[14px] font-medium text-[#281950] truncate">{target || 'Scan in progress'}</span>
          </div>
          {scanId && (
            <span className="font-mono text-[12px] text-[#a39ac1] shrink-0">ID: {scanId.slice(0, 12)}…</span>
          )}
        </div>

        {/* ── Stage Progress ── */}
        <div className="px-6 py-5">
          <div className="flex items-center justify-between relative">
            {/* Connector line */}
            <div className="absolute top-[15px] left-[calc(10%+8px)] right-[calc(10%+8px)] h-[2px] bg-[#e7e6f4]">
              <div
                className="h-full bg-[#7c3aed] transition-all duration-700 ease-out"
                style={{
                  width: isFailed
                    ? '100%'
                    : stageIdx >= 0
                      ? `${(stageIdx / (STAGES.length - 1)) * 100}%`
                      : '0%',
                }}
              />
            </div>
            {STAGES.map((stage, i) => {
              const isActive = i === stageIdx
              const isDone = i < stageIdx && !isFailed
              const isCurrentFailed = isFailed && i === STAGES.length - 1
              return (
                <div key={stage.key} className="relative z-10 flex flex-col items-center gap-2 w-[20%]">
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center border-2 transition-all duration-500 ${
                      isCurrentFailed
                        ? 'bg-red-50 border-red-500'
                        : isDone
                          ? 'bg-[#7c3aed] border-[#7c3aed]'
                          : isActive
                            ? 'bg-white border-[#7c3aed] shadow-md shadow-[#7c3aed]/20'
                            : 'bg-white border-[#e7e6f4]'
                    }`}
                  >
                    {isDone ? (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
                    ) : isCurrentFailed ? (
                      <AlertCircle className="w-4 h-4 text-red-500" />
                    ) : (
                      <stage.icon className={`w-4 h-4 ${isActive ? 'text-[#7c3aed]' : 'text-[#a39ac1]'}`} />
                    )}
                  </div>
                  <span
                    className={`font-body text-[11px] font-medium text-center leading-tight ${
                      isActive || isDone || isCurrentFailed ? 'text-[#281950]' : 'text-[#a39ac1]'
                    }`}
                  >
                    {isCurrentFailed ? 'Failed' : stage.label}
                  </span>
                </div>
              )
            })}
          </div>
        </div>

        {/* ── Terminal Log ── */}
        {(hasActiveScan || isCompleted || isFailed) && (
          <div className="px-6 pb-5">
            <div className="rounded-xl bg-[#1e1b2e] border border-white/10 p-4">
              <div className="flex items-center gap-2 mb-3">
                <Terminal className="w-3.5 h-3.5 text-[#c8bfff]" />
                <span className="font-mono text-[11px] text-[#c8bfff] uppercase tracking-wider">Scan Log</span>
              </div>
              <div className="space-y-1 font-mono text-[12px] leading-[18px]">
                {(() => {
                  const logs: string[] = []
                  const currentStageKey = isFailed ? 'completed' : status ?? 'queued'
                  const currentIdx = STAGES.findIndex((s) => s.key === currentStageKey)
                  const effectiveIdx = currentIdx >= 0 ? currentIdx : 0
                  for (let i = 0; i <= effectiveIdx; i++) {
                    const key = STAGES[i].key
                    const stageLogs = STAGE_LOGS[key] || []
                    if (i < effectiveIdx) {
                      stageLogs.forEach((line) => logs.push(line))
                    } else {
                      // For current stage, show all logs if completed/failed, or partial if active
                      const showCount = isCompleted || isFailed ? stageLogs.length : Math.max(1, Math.min(stageLogs.length, Math.floor((Date.now() / 2000) % (stageLogs.length + 1))))
                      stageLogs.slice(0, showCount).forEach((line) => logs.push(line))
                      if (!isCompleted && !isFailed && showCount < stageLogs.length) {
                        logs.push(stageLogs[showCount] + '…')
                      }
                    }
                  }
                  // Deduplicate while preserving order
                  const seen = new Set<string>()
                  const unique = logs.filter((l) => {
                    const base = l.replace(/…$/, '')
                    if (seen.has(base)) return false
                    seen.add(base)
                    return true
                  })
                  return unique.map((line, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <span className="text-[#5046e4] shrink-0 select-none">{'>'}</span>
                      <span className={line.includes('VULNERABILITY') || line.includes('error') || line.includes('Failed') ? 'text-red-300' : line.includes('complete') || line.includes('Opening PR') || line.includes('Generating fix') ? 'text-green-300' : 'text-white/70'}>
                        {line}
                      </span>
                    </div>
                  ))
                })()}
                {!isCompleted && !isFailed && (
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-[#5046e4] shrink-0">{'>'}</span>
                    <span className="text-white/40 animate-pulse">_</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── Error Banner ── */}
        {error && (
          <div className="px-6 pb-5">
            <div className="rounded-xl bg-red-50 border border-red-100 px-4 py-3 flex items-start gap-3">
              <AlertCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
              <span className="font-body text-[13px] text-red-700">{error}</span>
            </div>
          </div>
        )}

        {/* ── Findings Summary + Grid ── */}
        {isCompleted && sortedFindings && (
          <div className="px-6 pb-6">
            {/* Severity summary chips */}
            <div className="flex flex-wrap items-center gap-2 mb-5">
              <span className="font-body text-[13px] font-medium text-[#281950] mr-1">
                {sortedFindings.length} finding{sortedFindings.length !== 1 ? 's' : ''}
              </span>
              {SEVERITY_ORDER.map((sev) => {
                const count = severityCounts[sev] || 0
                if (count === 0) return null
                return (
                  <span
                    key={sev}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-body text-[11px] font-semibold uppercase tracking-wide border ${
                      sev === 'critical'
                        ? 'bg-red-50 text-red-700 border-red-100'
                        : sev === 'high'
                          ? 'bg-orange-50 text-orange-700 border-orange-100'
                          : sev === 'medium'
                            ? 'bg-yellow-50 text-yellow-700 border-yellow-100'
                            : sev === 'low'
                              ? 'bg-blue-50 text-blue-700 border-blue-100'
                              : 'bg-gray-50 text-gray-600 border-gray-100'
                    }`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${severityColor(sev)}`} />
                    {sev} <span className="opacity-70">{count}</span>
                  </span>
                )
              })}
            </div>

            {sortedFindings.length === 0 ? (
              <div className="rounded-xl bg-green-50 border border-green-100 px-4 py-6 text-center">
                <FileCheck className="w-6 h-6 text-green-500 mx-auto mb-2" />
                <p className="font-body text-[14px] text-green-700 font-medium">No findings — scan completed clean.</p>
              </div>
            ) : (
              <div className="grid gap-3">
                {sortedFindings.map((finding) => (
                  <FindingCard key={finding.id ?? finding.title} finding={finding} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
