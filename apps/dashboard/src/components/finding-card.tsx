'use client'

import { AlertCircle, AlertTriangle, ShieldAlert, Info, FileCode2 } from 'lucide-react'

const SEVERITY_CONFIG: Record<string, { label: string; icon: typeof AlertCircle; badgeClass: string; dotClass: string }> = {
  critical: {
    label: 'Critical',
    icon: ShieldAlert,
    badgeClass: 'bg-red-50 text-red-700 border-red-100',
    dotClass: 'bg-red-500',
  },
  high: {
    label: 'High',
    icon: AlertTriangle,
    badgeClass: 'bg-orange-50 text-orange-700 border-orange-100',
    dotClass: 'bg-orange-500',
  },
  medium: {
    label: 'Medium',
    icon: AlertCircle,
    badgeClass: 'bg-yellow-50 text-yellow-700 border-yellow-100',
    dotClass: 'bg-yellow-500',
  },
  low: {
    label: 'Low',
    icon: Info,
    badgeClass: 'bg-blue-50 text-blue-700 border-blue-100',
    dotClass: 'bg-blue-500',
  },
  info: {
    label: 'Info',
    icon: Info,
    badgeClass: 'bg-gray-50 text-gray-600 border-gray-100',
    dotClass: 'bg-gray-400',
  },
}

interface Finding {
  id?: string | number
  severity?: string
  title?: string
  description?: string
  file_path?: string
  line?: number
  tier?: string
  model_source?: string
  poc_curl?: string
  remediation_code?: string
}

interface FindingCardProps {
  finding: Finding
}

export function FindingCard({ finding }: FindingCardProps) {
  const sev = (finding.severity ?? 'info').toLowerCase()
  const config = SEVERITY_CONFIG[sev] || SEVERITY_CONFIG.info
  const Icon = config.icon

  return (
    <div className="rounded-xl bg-white border border-[#e7e6f4] hover:shadow-md hover:border-[#d4d2e8] transition-all overflow-hidden">
      {/* Header: severity badge + title */}
      <div className="px-5 py-4 border-b border-[#e7e6f4] flex flex-col sm:flex-row sm:items-start gap-3">
        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-body text-[11px] font-semibold uppercase tracking-wide border shrink-0 self-start ${config.badgeClass}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${config.dotClass}`} />
          <Icon className="w-3 h-3" />
          {config.label}
        </span>
        <h4 className="font-body text-[15px] font-semibold text-[#281950] leading-snug">
          {finding.title || 'Untitled Finding'}
        </h4>
      </div>

      {/* Body: file path, line, description */}
      <div className="px-5 py-4 space-y-3">
        {/* File path + line */}
        {finding.file_path && (
          <div className="flex items-center gap-2 text-[13px]">
            <FileCode2 className="w-3.5 h-3.5 text-[#a39ac1] shrink-0" />
            <span className="font-mono text-[#5e537c] truncate">{finding.file_path}</span>
            {finding.line !== undefined && finding.line !== null && (
              <span className="font-mono text-[11px] text-[#a39ac1] shrink-0">:{finding.line}</span>
            )}
          </div>
        )}

        {/* Description */}
        {finding.description && (
          <p className="font-body text-[14px] leading-[22px] text-[#5e537c]">
            {finding.description}
          </p>
        )}

        {/* Tier + model source chips */}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          {finding.tier && (
            <span className="px-2 py-0.5 rounded-md bg-[#f1f2f9] font-mono text-[11px] text-[#7c3aed] border border-[#e7e6f4]">
              Tier {finding.tier}
            </span>
          )}
          {finding.model_source && (
            <span className="px-2 py-0.5 rounded-md bg-[#f1f2f9] font-mono text-[11px] text-[#5e537c] border border-[#e7e6f4]">
              {finding.model_source}
            </span>
          )}
        </div>

        {/* PoC curl (collapsible-ish, just truncated) */}
        {finding.poc_curl && (
          <div className="rounded-lg bg-[#1e1b2e] border border-white/10 p-3 mt-2">
            <p className="font-mono text-[11px] text-[#c8bfff] uppercase tracking-wider mb-1.5">Proof of Concept</p>
            <code className="font-mono text-[12px] text-white/80 block whitespace-pre-wrap break-all leading-[18px]">
              {finding.poc_curl}
            </code>
          </div>
        )}

        {/* Remediation code */}
        {finding.remediation_code && (
          <div className="rounded-lg bg-[#f1f2f9] border border-[#e7e6f4] p-3 mt-2">
            <p className="font-body text-[11px] font-semibold text-[#281950] uppercase tracking-wider mb-1.5">Suggested Fix</p>
            <code className="font-mono text-[12px] text-[#5e537c] block whitespace-pre-wrap break-all leading-[18px]">
              {finding.remediation_code}
            </code>
          </div>
        )}
      </div>
    </div>
  )
}
