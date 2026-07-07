"use client";

import { useState } from "react";
import { SeverityBadge } from "./severity-badge";
import { ChevronDownIcon, CopyIcon, CodeIcon, LockIcon } from "./icons";

interface Finding {
  severity: string;
  title: string;
  file?: string;
  line?: number;
  description?: string;
  code?: string;
  poc?: string;
  remediation?: string;
  cwe?: string;
  cvss?: number;
}

const severityBorderColors: Record<string, string> = {
  critical: "#EF4444",
  high: "#F59E0B",
  medium: "#EAB308",
  low: "#3B82F6",
  info: "#6B7280",
};

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 px-2 py-1 text-xs text-av-text-muted hover:text-av-text-primary transition-colors"
    >
      <CopyIcon className="w-3.5 h-3.5" />
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function FindingCard({ finding, index }: { finding: Finding; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const [showPoc, setShowPoc] = useState(false);

  const borderColor = severityBorderColors[finding.severity] || severityBorderColors.info;

  return (
    <div
      className="bg-av-surface border border-av-border rounded-lg overflow-hidden av-animate-fade-in"
      style={{
        borderLeft: `4px solid ${borderColor}`,
        animationDelay: `${Math.min(index * 50, 300)}ms`,
      }}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-5 py-4 text-left hover:bg-av-surface-hover transition-colors"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-semibold text-av-text-primary mb-1">
              {finding.title}
            </h3>
            {finding.file && (
              <p className="font-mono text-xs text-av-text-muted">
                {finding.file}
                {finding.line ? `:${finding.line}` : ""}
              </p>
            )}
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            <SeverityBadge severity={finding.severity} />
            <ChevronDownIcon
              className={`w-4 h-4 text-av-text-muted transition-transform duration-200 ${
                expanded ? "rotate-180" : ""
              }`}
            />
          </div>
        </div>
        {finding.description && !expanded && (
          <p className="mt-2 text-sm text-av-text-secondary line-clamp-2">
            {finding.description}
          </p>
        )}
      </button>

      {expanded && (
        <div className="px-5 pb-5 space-y-4 av-animate-slide-down">
          {finding.description && (
            <div>
              <h4 className="text-xs font-medium text-av-text-muted uppercase tracking-wide mb-2">
                Description
              </h4>
              <p className="text-sm text-av-text-secondary leading-relaxed">
                {finding.description}
              </p>
            </div>
          )}

          {finding.code && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-xs font-medium text-av-text-muted uppercase tracking-wide flex items-center gap-1.5">
                  <CodeIcon className="w-3.5 h-3.5" />
                  Code
                </h4>
                <CopyButton text={finding.code} />
              </div>
              <pre className="bg-av-bg border border-av-border rounded-md p-3 overflow-x-auto">
                <code className="font-mono text-xs text-av-text-secondary whitespace-pre">
                  {finding.code}
                </code>
              </pre>
            </div>
          )}

          {finding.poc && (
            <div>
              <button
                onClick={() => setShowPoc(!showPoc)}
                className="flex items-center gap-1.5 text-xs font-medium text-av-primary hover:text-av-primary-hover transition-colors mb-2"
              >
                <LockIcon className="w-3.5 h-3.5" />
                {showPoc ? "Hide PoC" : "Show PoC"}
              </button>
              {showPoc && (
                <div className="av-animate-slide-down">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-av-text-muted">Proof of Concept</span>
                    <CopyButton text={finding.poc} />
                  </div>
                  <pre className="bg-av-bg border border-av-border rounded-md p-3 overflow-x-auto">
                    <code className="font-mono text-xs text-av-critical whitespace-pre">
                      {finding.poc}
                    </code>
                  </pre>
                </div>
              )}
            </div>
          )}

          {finding.remediation && (
            <div>
              <h4 className="text-xs font-medium text-av-text-muted uppercase tracking-wide mb-2">
                Remediation
              </h4>
              <div className="bg-green-500/5 border border-green-500/20 rounded-md p-3">
                <p className="text-sm text-green-400">{finding.remediation}</p>
              </div>
            </div>
          )}

          {(finding.cwe || finding.cvss) && (
            <div className="flex items-center gap-2 pt-2 border-t border-av-border">
              {finding.cwe && (
                <span className="px-2 py-0.5 text-xs font-mono bg-av-bg border border-av-border rounded text-av-text-muted">
                  {finding.cwe}
                </span>
              )}
              {finding.cvss && (
                <span className="px-2 py-0.5 text-xs font-mono bg-av-bg border border-av-border rounded text-av-text-muted">
                  CVSS {finding.cvss.toFixed(1)}
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
