import type { RunStatus } from "@/api/types";
import { cn } from "@/lib/utils";

const CONFIG: Record<string, { label: string; text: string; bg: string; dot: string }> = {
  succeeded: { label: "Succeeded", text: "text-[#16784A]", bg: "bg-ok-bg", dot: "bg-ok" },
  failed: { label: "Failed", text: "text-[#B0342B]", bg: "bg-err-bg", dot: "bg-err" },
  running: { label: "Running", text: "text-[#8C6108]", bg: "bg-run-bg", dot: "bg-run" },
};

export function StatusPill({ status }: { status: RunStatus | null | undefined }) {
  const cfg = status ? CONFIG[status] : undefined;
  if (!cfg) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-panel px-2 py-0.5 text-xs text-ink-3">
        <span className="h-[7px] w-[7px] rounded-full bg-line-2" />
        Never run
      </span>
    );
  }
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs", cfg.bg, cfg.text)}>
      <span className={cn("h-[7px] w-[7px] rounded-full", cfg.dot)} />
      {cfg.label}
    </span>
  );
}
