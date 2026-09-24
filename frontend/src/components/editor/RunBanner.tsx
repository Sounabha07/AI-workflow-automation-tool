import { AlertTriangle, CircleCheck, Loader2 } from "lucide-react";
import type { RunDetailResponse } from "@/api/types";
import { Button } from "@/components/ui/button";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";

const STYLE: Record<string, string> = {
  failed: "bg-err-bg border-[#F2C4BF] text-[#8E2A22]",
  succeeded: "bg-ok-bg border-[#BFE3CD] text-[#16784A]",
  running: "bg-run-bg border-[#EED9A6] text-[#8C6108]",
};

export function RunBanner({
  run,
  onBack,
  onOpenCurrent,
}: {
  run: RunDetailResponse;
  onBack: () => void;
  onOpenCurrent: () => void;
}) {
  const at = relativeTime(run.started_at ?? run.created_at);
  const failingBlock = run.error_summary?.block_id;

  const Icon = run.status === "failed" ? AlertTriangle : run.status === "running" ? Loader2 : CircleCheck;

  const message =
    run.status === "failed" ? (
      <span>
        Run <span className="font-mono">{run.id.slice(0, 8)}</span> from {at} failed at{" "}
        <b>{failingBlock}</b>. Double-click it to see the error.
      </span>
    ) : run.status === "running" ? (
      <span>
        Run <span className="font-mono">{run.id.slice(0, 8)}</span> started {at} and is still running.
      </span>
    ) : (
      <span>
        Run <span className="font-mono">{run.id.slice(0, 8)}</span> from {at} succeeded.
      </span>
    );

  return (
    <div
      className={cn(
        "absolute inset-x-0 top-0 z-[4] flex h-[46px] items-center gap-2.5 border-b px-4 text-[13px]",
        STYLE[run.status] ?? STYLE.running
      )}
    >
      <Icon className={cn("h-4 w-4", run.status === "running" && "animate-spin")} aria-hidden="true" />
      {message}
      <span className="flex-1" />
      <Button onClick={onBack}>Back to history</Button>
      <Button onClick={onOpenCurrent}>Open current version</Button>
    </div>
  );
}
