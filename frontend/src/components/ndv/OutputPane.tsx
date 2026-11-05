import { AlertTriangle, Ban, CircleCheck, FlaskConical, Loader2, SkipForward, Square } from "lucide-react";
import type { BlockError } from "@/api/types";
import { retryHint } from "@/lib/errorHints";
import { DataView, type ViewMode } from "./DataView";
import { ModeToggle } from "./InputPane";
import { ResumePanel } from "./ResumePanel";
import { AgentSummary, AgentTrace } from "./AgentOutput";
import type { AgentTraceStep } from "@/api/types";
import { useEditorStore, type NodeRuntimeStatus } from "@/store/editor";

function Empty({ icon: Icon, children }: { icon: React.ComponentType<{ className?: string }>; children: React.ReactNode }) {
  return (
    <div className="grid h-full place-items-center px-6 text-center text-[13px] text-ink-3">
      <div>
        <Icon className="mx-auto mb-2 h-7 w-7" />
        {children}
      </div>
    </div>
  );
}

export function OutputPane({
  blockId,
  blockType,
  isTool,
  status,
  output,
  error,
  durationMs,
  stoppedAtBlockId,
  resumeUrl,
  waitDeadline,
  mode,
  onModeChange,
}: {
  blockId: string;
  blockType?: string;
  isTool?: boolean;
  status: NodeRuntimeStatus;
  output: Record<string, unknown> | null;
  error: BlockError | null;
  durationMs: number | null;
  stoppedAtBlockId?: string;
  resumeUrl?: string | null;
  waitDeadline?: string | null;
  mode: ViewMode;
  onModeChange: (mode: ViewMode) => void;
}) {
  const isAgent = blockType === "agent";
  const activity = useEditorStore((s) => (isAgent ? s.agentActivity[blockId] : null));
  const detail = (error?.detail ?? null) as Record<string, unknown> | null;
  if (isTool) {
    return (
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex h-12 items-center border-b border-line px-4">
          <h3 className="m-0 text-xs font-semibold text-ink-2">Output</h3>
        </div>
        <Empty icon={Square}>
          This block is a tool: it runs only when its agent calls it. Its calls and results are in the agent's trace. Use
          Test tool to call it on its own.
        </Empty>
      </div>
    );
  }
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="flex h-12 items-center gap-2 border-b border-line px-4">
        <h3 className="m-0 text-xs font-semibold text-ink-2">Output</h3>
        <span className="flex-1" />
        <ModeToggle mode={mode} onModeChange={onModeChange} />
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">
        {status === "failed" && error ? (
          <div className="rounded-lg border border-[#F2C4BF] bg-err-bg p-3">
            <div className="mb-2 flex items-center gap-2 text-[13px] text-[#B0342B]">
              <AlertTriangle className="h-4 w-4" />
              <b>This block failed</b>
              <span className="ml-auto text-xs text-ink-3">
                {error.attempts} {error.attempts === 1 ? "attempt" : "attempts"}
              </span>
            </div>
            <pre className="m-0 whitespace-pre-wrap break-words rounded-md border border-[#F2C4BF] bg-surface p-2.5 font-mono text-xs leading-relaxed">
              {error.message}
            </pre>
            <div className="mt-2 text-xs text-ink-2">{retryHint(error)}</div>
            {isAgent && detail && (
              <div className="mt-3 rounded-md bg-surface p-3">
                <AgentSummary
                  stopReason={detail.stop_reason}
                  iterations={detail.iterations}
                  toolCalls={detail.tool_calls}
                  usage={detail.usage}
                />
                <AgentTrace trace={(detail.trace as AgentTraceStep[]) ?? []} />
              </div>
            )}
          </div>
        ) : status === "waiting" ? (
          <ResumePanel blockId={blockId} resumeUrl={resumeUrl} waitDeadline={waitDeadline} />
        ) : status === "cancelled" ? (
          <Empty icon={Ban}>Cancelled: the run failed in another branch while this block was waiting.</Empty>
        ) : status === "not_run" || status === "pending" ? (
          <Empty icon={Square}>
            {stoppedAtBlockId
              ? `Didn't run because the workflow stopped at ${stoppedAtBlockId}.`
              : "Waiting for earlier blocks to finish."}
          </Empty>
        ) : status === "running" ? (
          <Empty icon={Loader2}>
            {isAgent && activity ? `Agent: ${activity}` : "Running now. The output appears here when it finishes."}
          </Empty>
        ) : status === "skipped" ? (
          <Empty icon={SkipForward}>Skipped because the switch sent data down a different output.</Empty>
        ) : !output ? (
          <Empty icon={FlaskConical}>Test this block to see its output here.</Empty>
        ) : (
          <>
            <div className="mb-3 flex items-center gap-2.5 text-xs">
              <span className="flex items-center gap-1.5 text-ok">
                <CircleCheck className="h-3.5 w-3.5" />
                Succeeded{durationMs !== null ? ` in ${durationMs} ms` : ""}
              </span>
              <span className="text-ink-3">1 item</span>
            </div>
            {isAgent ? (
              <>
                <AgentSummary
                  final={output.final}
                  stopReason={output.stop_reason}
                  iterations={output.iterations}
                  toolCalls={output.tool_calls}
                  usage={output.usage}
                />
                <AgentTrace trace={(output.trace as AgentTraceStep[]) ?? []} />
                <h4 className="mb-2 mt-4 text-xs font-semibold text-ink-2">Output fields</h4>
                <DataView
                  data={{ ...output, trace: `${(output.trace as unknown[] | undefined)?.length ?? 0} steps` }}
                  mode={mode}
                  baseId={blockId}
                />
              </>
            ) : (
              <DataView data={output} mode={mode} baseId={blockId} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
