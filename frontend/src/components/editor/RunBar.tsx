import { useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { getRun, getRunBlocks } from "@/api/runs";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/StatusPill";
import { formatDuration } from "@/lib/time";

export function RunBar({
  runId,
  onRun,
  running,
}: {
  runId: string | null;
  onRun: () => void;
  running: boolean;
}) {
  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId!),
    enabled: !!runId,
  });
  const { data: blocks } = useQuery({
    queryKey: ["runBlocks", runId],
    queryFn: () => getRunBlocks(runId!),
    enabled: !!runId,
  });

  const blocksRan = blocks?.filter((b) => b.status === "succeeded" || b.status === "failed").length ?? 0;
  const skipped = blocks?.filter((b) => b.status === "skipped").length ?? 0;
  const durationMs =
    run?.started_at && run?.finished_at
      ? new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()
      : null;

  return (
    <div className="absolute bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-3 whitespace-nowrap rounded-[10px] border border-line bg-surface py-1.5 pl-3.5 pr-1.5 text-xs text-ink-2 shadow-sm">
      {run ? (
        <>
          <StatusPill status={run.status} />
          <span>
            {blocksRan} blocks ran{skipped ? `, ${skipped} skipped` : ""}
            {durationMs !== null ? `, ${formatDuration(durationMs)}` : ""}
          </span>
        </>
      ) : (
        <span>This workflow hasn't run yet</span>
      )}
      <Button variant="primary" onClick={onRun} disabled={running}>
        <Play className="h-3.5 w-3.5" aria-hidden="true" />
        {running ? "Running…" : "Run workflow"}
      </Button>
    </div>
  );
}
