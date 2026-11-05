import { useState } from "react";
import { Bot, ChevronDown, ChevronRight, CircleCheck, HelpCircle, RotateCcw, Wrench, X } from "lucide-react";
import type { AgentTraceStep } from "@/api/types";
import { Pre } from "./ToolPanels";
import { cn } from "@/lib/utils";

function fmtMs(ms: number | null | undefined) {
  if (ms == null) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-md border border-line bg-surface px-2.5 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-ink-3">{label}</div>
      <div className="font-mono text-xs">{value}</div>
    </div>
  );
}

function Step({ step }: { step: AgentTraceStep }) {
  const [open, setOpen] = useState(false);
  const isTool = step.kind === "tool";
  const failed = step.status === "failed";
  const Icon = isTool ? Wrench : Bot;
  const title = isTool
    ? step.tool_name
    : step.status === "failed"
      ? "Model call failed"
      : step.tool_calls?.length
        ? `Model asked for ${step.tool_calls.map((c) => c.name).join(", ")}`
        : "Model answered";

  return (
    <li className="relative pl-6">
      <span
        className={cn(
          "absolute left-0 top-1 grid h-4 w-4 place-items-center rounded-full text-white",
          failed ? "bg-err" : step.status === "started" ? "bg-run" : isTool ? "bg-llm" : "bg-ink-3"
        )}
      >
        <Icon className="h-2.5 w-2.5" />
      </span>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 border-0 bg-transparent p-0 text-left text-xs text-ink"
      >
        {open ? <ChevronDown className="h-3 w-3 text-ink-3" /> : <ChevronRight className="h-3 w-3 text-ink-3" />}
        <span className={cn("font-medium", isTool && "font-mono")}>{title}</span>
        {step.outcome_unknown && (
          <span className="flex items-center gap-0.5 text-[#9A6B00]" title="The worker stopped mid-call; not repeated">
            <HelpCircle className="h-3 w-3" /> outcome unknown
          </span>
        )}
        {failed && !step.outcome_unknown && <X className="h-3 w-3 text-err" />}
        {step.status === "completed" && isTool && <CircleCheck className="h-3 w-3 text-ok" />}
        {step.replayed && (
          <span className="flex items-center gap-0.5 rounded bg-panel px-1 text-[10px] text-ink-3" title="From an earlier attempt; not re-run">
            <RotateCcw className="h-2.5 w-2.5" /> replayed
          </span>
        )}
        <span className="ml-auto text-[11px] text-ink-3">{fmtMs(step.duration_ms)}</span>
      </button>
      {!isTool && step.text && !open && <p className="m-0 mt-0.5 line-clamp-2 text-xs text-ink-2">{step.text}</p>}
      {open && (
        <div className="mt-1.5 space-y-2">
          {!isTool && step.text && <Pre label="Text" value={step.text} />}
          {!isTool && step.tool_calls?.length ? <Pre label="Tool calls" value={step.tool_calls} /> : null}
          {!isTool && step.nudge && <Pre label="Sent back" value={step.nudge} />}
          {!isTool && step.usage && <Pre label="Usage" value={step.usage} />}
          {isTool && <Pre label="Args" value={step.args} />}
          {isTool && step.request && <Pre label="Request" value={step.request} />}
          {isTool && step.response && <Pre label="The model saw" value={step.response} />}
          {isTool && step.result != null && <Pre label="Full result" value={step.result} />}
          {step.error && <Pre label="Error" value={step.error} />}
        </div>
      )}
    </li>
  );
}

export function AgentTrace({ trace }: { trace: AgentTraceStep[] }) {
  if (!trace.length) return null;
  return (
    <div>
      <h4 className="mb-2 mt-0 text-xs font-semibold text-ink-2">Trace</h4>
      <ol className="m-0 list-none space-y-2.5 border-l border-line p-0 pl-0">{trace.map((s, i) => <Step key={i} step={s} />)}</ol>
    </div>
  );
}

export function AgentSummary({
  final,
  stopReason,
  iterations,
  toolCalls,
  usage,
}: {
  final?: unknown;
  stopReason: unknown;
  iterations: unknown;
  toolCalls: unknown;
  usage: unknown;
}) {
  const u = (usage ?? {}) as Record<string, number | null>;
  return (
    <div className="mb-4 space-y-3">
      {final !== undefined && <Pre label="Final" value={final} />}
      <div className="grid grid-cols-2 gap-2">
        <Stat label="Stop reason" value={String(stopReason ?? "")} />
        <Stat label="Iterations" value={String(iterations ?? "")} />
        <Stat label="Tool calls" value={String(toolCalls ?? "")} />
        <Stat label="Tokens" value={u.total_tokens != null ? `${u.total_tokens} (${u.input_tokens ?? "?"} in, ${u.output_tokens ?? "?"} out)` : "n/a"} />
      </div>
    </div>
  );
}
