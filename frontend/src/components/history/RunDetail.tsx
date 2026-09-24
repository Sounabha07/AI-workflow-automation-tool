import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Copy, Network, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { getRunBlocks } from "@/api/runs";
import { triggerRun } from "@/api/runs";
import type { RunListItem } from "@/api/types";
import { ApiError } from "@/api/client";
import { applyPipelineActive } from "@/lib/pipelineCache";
import { Button } from "@/components/ui/button";
import { retryHint } from "@/lib/errorHints";
import { STATUS_DOT_CLASS, STATUS_LABEL } from "@/lib/statusVisuals";
import type { NodeRuntimeStatus } from "@/store/editor";

export function RunDetail({ run }: { run: RunListItem }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: blocks } = useQuery({
    queryKey: ["runBlocks", run.id],
    queryFn: () => getRunBlocks(run.id),
  });

  const runAgain = useMutation({
    mutationFn: () => triggerRun(run.pipeline_id, run.input_data ?? {}),
    onSuccess: ({ pipeline_is_active }) => {
      applyPipelineActive(queryClient, run.pipeline_id, pipeline_is_active);
      toast.success("Run started");
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't start the run"),
  });

  const copyError = () => {
    if (!run.error_summary) return;
    navigator.clipboard
      ?.writeText(`${run.error_summary.block_id}: ${run.error_summary.message}`)
      .then(() => toast.success("Copied"));
  };

  const left = run.error_summary ? (
    <div className="rounded-lg border border-[#F2C4BF] bg-err-bg p-3">
      <div className="mb-2 flex items-center gap-2 text-[13px] text-[#B0342B]">
        <AlertTriangle className="h-4 w-4" aria-hidden="true" />
        <b>{run.error_summary.block_id}</b> failed
        <span className="ml-auto text-xs text-ink-3">
          {run.error_summary.type} block, {run.error_summary.attempts}{" "}
          {run.error_summary.attempts === 1 ? "attempt" : "attempts"}
        </span>
      </div>
      <pre className="m-0 whitespace-pre-wrap break-words rounded-md border border-[#F2C4BF] bg-surface p-2.5 font-mono text-xs leading-relaxed">
        {run.error_summary.message}
      </pre>
      <div className="mt-2 text-xs text-ink-2">{retryHint(run.error_summary)}</div>
    </div>
  ) : (
    <div className="rounded-lg border border-line bg-surface p-3 text-[13px] text-ink-2">
      {run.status === "running"
        ? "This run is still in progress. Block statuses update live."
        : "All blocks that ran finished without errors."}
    </div>
  );

  return (
    <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] gap-4 border-t border-line bg-panel p-4">
      {left}
      <div className="rounded-lg border border-line bg-surface p-2.5">
        <h4 className="mb-1.5 mt-0.5 text-xs font-semibold text-ink-2">Blocks in this run</h4>
        {(blocks ?? []).map((b) => (
          <div key={b.block_id} className="flex items-center gap-2 py-1 text-xs">
            <span className={`h-2 w-2 flex-none rounded-full ${STATUS_DOT_CLASS[b.status as NodeRuntimeStatus]}`} />
            <span className={b.status === "failed" ? "font-semibold text-[#B0342B]" : ""}>{b.block_id}</span>
            <span className="ml-auto text-ink-3">{STATUS_LABEL[b.status as NodeRuntimeStatus]}</span>
          </div>
        ))}
      </div>
      <div className="col-span-2 flex gap-2">
        <Button onClick={() => navigate(`/workflows/${run.pipeline_id}/runs/${run.id}`)}>
          <Network className="h-3.5 w-3.5" aria-hidden="true" />
          Open run on canvas
        </Button>
        {run.error_summary && (
          <Button onClick={copyError}>
            <Copy className="h-3.5 w-3.5" aria-hidden="true" />
            Copy error
          </Button>
        )}
        <Button onClick={() => runAgain.mutate()} disabled={runAgain.isPending}>
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          Run again
        </Button>
      </div>
    </div>
  );
}
