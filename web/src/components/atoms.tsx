import { TERRITORY, VERDICT_LABEL, VERDICT_SHORT } from "@/lib/territories";
import type { Output, StoryStatus, Verdict } from "@/lib/types";

export function VerdictChip({ verdict, short = false }: { verdict: Verdict; short?: boolean }) {
  return (
    <span className="chip verdict" data-verdict={verdict}>
      {short ? VERDICT_SHORT[verdict] : VERDICT_LABEL[verdict]}
    </span>
  );
}

export function TerritoryChip({ territory }: { territory: Output | string }) {
  const info = TERRITORY[territory as Output];
  return (
    <span className="chip territory" data-territory={territory} title={info?.label}>
      {info?.code ?? territory.toUpperCase()}
    </span>
  );
}

export function StatusChip({ status }: { status: StoryStatus | string }) {
  return (
    <span className="chip chip-dot status" data-status={status}>
      {status}
    </span>
  );
}

export type Health = "ok" | "degraded" | "failed" | "skipped" | "pending" | "running";

export function healthOf(status: string | undefined): Health {
  if (!status) return "pending";
  if (status === "ok" || status === "decided") return "ok";
  if (status.startsWith("degraded")) return "degraded";
  if (status.startsWith("failed") || status.startsWith("error")) return "failed";
  if (status === "skipped") return "skipped";
  return "ok";
}
