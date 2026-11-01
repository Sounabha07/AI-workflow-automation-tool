import type { NodeRuntimeStatus } from "@/store/editor";

/** B7's Input pane "why there's no data" copy. */
export function noDataText(blockId: string, status: NodeRuntimeStatus): string {
  if (status === "skipped") return "Skipped in this run.";
  if (status === "cancelled") return "Cancelled because the run failed elsewhere.";
  if (status === "waiting") return "Waiting for input. Its output appears once it's resumed.";
  if (status === "failed") return "This block failed, so it produced no output.";
  if (status === "not_run" || status === "pending") {
    return "Didn't run because the workflow stopped earlier.";
  }
  return `No data yet. Test ${blockId} to see its output.`;
}
