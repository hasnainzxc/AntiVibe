import { CheckIcon } from "./icons";

type ScanStep = "queued" | "cloning" | "analyzing" | "sandbox" | "complete";

const steps: { key: ScanStep; label: string }[] = [
  { key: "queued", label: "Queued" },
  { key: "cloning", label: "Cloning" },
  { key: "analyzing", label: "Analyzing" },
  { key: "sandbox", label: "Sandbox" },
  { key: "complete", label: "Complete" },
];

function getStepIndex(status: string | null): number {
  if (!status) return -1;
  const s = status.toLowerCase();
  if (s === "queued" || s === "starting") return 0;
  if (s === "cloning") return 1;
  if (s === "analyzing" || s === "running") return 2;
  if (s === "sandbox") return 3;
  if (s === "completed" || s === "complete") return 4;
  return -1;
}

export function ScanProgress({ status, logs }: { status: string | null; logs?: string[] }) {
  const currentIndex = getStepIndex(status);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        {steps.map((step, i) => {
          const isDone = i < currentIndex;
          const isActive = i === currentIndex;
          const isPending = i > currentIndex;

          return (
            <div key={step.key} className="flex items-center flex-1 last:flex-none">
              <div className="flex flex-col items-center">
                <div
                  className={`
                    w-8 h-8 rounded-full flex items-center justify-center border-2 transition-all duration-300
                    ${isDone ? "border-green-500 bg-green-500/20" : ""}
                    ${isActive ? "border-av-primary bg-av-primary/20 av-animate-pulse" : ""}
                    ${isPending ? "border-av-border bg-transparent" : ""}
                  `}
                  style={isActive ? { boxShadow: "0 0 20px rgba(99,102,241,0.15)" } : {}}
                >
                  {isDone && <CheckIcon className="w-4 h-4 text-green-500" />}
                  {isActive && <div className="w-2 h-2 rounded-full bg-av-primary" />}
                  {isPending && <div className="w-2 h-2 rounded-full bg-av-border" />}
                </div>
                <span
                  className={`
                    mt-2 text-xs font-medium transition-colors
                    ${isDone ? "text-green-500" : ""}
                    ${isActive ? "text-av-primary" : ""}
                    ${isPending ? "text-av-text-muted" : ""}
                  `}
                >
                  {step.label}
                </span>
              </div>
              {i < steps.length - 1 && (
                <div
                  className={`
                    flex-1 h-0.5 mx-3 transition-colors duration-300
                    ${i < currentIndex ? "bg-green-500" : "bg-av-border"}
                  `}
                />
              )}
            </div>
          );
        })}
      </div>

      {logs && logs.length > 0 && (
        <div className="bg-av-surface border border-av-border rounded-lg p-4">
          <div className="space-y-1">
            {logs.slice(-3).map((log, i) => (
              <div
                key={i}
                className="font-mono text-xs text-av-text-secondary av-animate-fade-in"
                style={{ animationDelay: `${i * 50}ms` }}
              >
                {log}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
