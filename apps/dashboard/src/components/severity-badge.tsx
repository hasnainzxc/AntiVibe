import { SeverityDot } from "./icons";

type Severity = "critical" | "high" | "medium" | "low" | "info";

const severityConfig: Record<Severity, { color: string; bg: string; label: string }> = {
  critical: { color: "#EF4444", bg: "rgba(239,68,68,0.15)", label: "Critical" },
  high: { color: "#F59E0B", bg: "rgba(245,158,11,0.15)", label: "High" },
  medium: { color: "#EAB308", bg: "rgba(234,179,8,0.15)", label: "Medium" },
  low: { color: "#3B82F6", bg: "rgba(59,130,246,0.15)", label: "Low" },
  info: { color: "#6B7280", bg: "rgba(107,114,128,0.15)", label: "Info" },
};

export function SeverityBadge({ severity }: { severity: Severity | string }) {
  const config = severityConfig[severity as Severity] || severityConfig.info;

  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
      style={{ backgroundColor: config.bg, color: config.color }}
    >
      <SeverityDot color={config.color} className="w-2 h-2" />
      {config.label}
    </span>
  );
}

export function SeverityCounter({ severity, count }: { severity: Severity | string; count: number }) {
  const config = severityConfig[severity as Severity] || severityConfig.info;

  return (
    <div
      className="flex items-center gap-2 px-4 py-2 rounded-lg"
      style={{ backgroundColor: config.bg }}
    >
      <SeverityDot color={config.color} className="w-2.5 h-2.5" />
      <span className="text-sm font-medium" style={{ color: config.color }}>
        {config.label}
      </span>
      <span className="text-lg font-bold" style={{ color: config.color }}>
        {count}
      </span>
    </div>
  );
}
