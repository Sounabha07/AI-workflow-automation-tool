import type { NodeRuntimeStatus } from "@/store/editor";

export const STATUS_LABEL: Record<NodeRuntimeStatus, string> = {
  idle: "Idle",
  pending: "Waiting",
  ready: "Waiting",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  skipped: "Skipped",
  waiting: "Waiting",
  not_run: "Not run",
};

export const STATUS_DOT_CLASS: Record<NodeRuntimeStatus, string> = {
  idle: "bg-line-2",
  pending: "bg-line-2",
  ready: "bg-line-2",
  running: "bg-run",
  succeeded: "bg-ok",
  failed: "bg-err",
  skipped: "bg-[#9AA4B2]",
  waiting: "bg-line-2",
  not_run: "bg-line-2",
};
