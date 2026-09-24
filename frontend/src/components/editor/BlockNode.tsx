import { memo, useEffect } from "react";
import { Handle, Position, useUpdateNodeInternals, type NodeProps } from "@xyflow/react";
import { AlertTriangle, Check, SkipForward } from "lucide-react";
import { blockVisual, COLOR_TEXT_CLASS } from "@/lib/blockVisuals";
import { nodeSubtitle, switchOutputs } from "@/lib/nodeSubtitle";
import type { FlowNode } from "@/lib/definition";
import { useEditorStore } from "@/store/editor";
import { cn } from "@/lib/utils";

export const NODE_WIDTH = 88;

export function boxHeight(blockType: string, config: Record<string, unknown>): number {
  if (blockType !== "switch") return NODE_WIDTH;
  const n = switchOutputs(config).length;
  return Math.max(NODE_WIDTH, 24 + n * 34);
}

function handleTop(index: number, count: number, height: number): number {
  return (height / (count + 1)) * (index + 1);
}

const BORDER_BY_STATUS: Record<string, string> = {
  succeeded: "border-ok",
  failed: "border-err",
  running: "border-run animate-pulse-run",
  skipped: "border-dashed border-[#B8C0CC]",
  not_run: "border-dashed border-line-2 opacity-55",
  pending: "border-dashed border-line-2 opacity-55",
  waiting: "border-dashed border-line-2 opacity-55",
  ready: "border-line-2",
  idle: "border-line-2",
};

export const BlockNode = memo(function BlockNode({ id, data, selected }: NodeProps<FlowNode>) {
  const visual = blockVisual(data.blockType);
  const Icon = visual.icon;
  const state = useEditorStore((s) => s.blockStates[id]);
  const status = state?.status ?? "idle";
  const height = boxHeight(data.blockType, data.config);
  const outputs = data.blockType === "switch" ? switchOutputs(data.config) : ["main"];
  const subtitle = nodeSubtitle(data);

  const openEditor = useEditorStore((s) => s.setOpenBlockId);

  // Switch outputs (and so handles) can change after the node has already
  // mounted — adding/removing/renaming a rule — and React Flow caches each
  // node's handle positions for connection hit-testing. Without this, a
  // newly added handle renders fine but silently can't be connected to.
  const updateNodeInternals = useUpdateNodeInternals();
  const outputsKey = outputs.join(",");
  useEffect(() => {
    updateNodeInternals(id);
  }, [id, outputsKey, height, updateNodeInternals]);

  return (
    <div className="flex w-[150px] flex-col items-center select-none">
      <div
        role="button"
        tabIndex={0}
        aria-label={`${id} block`}
        onDoubleClick={() => openEditor(id)}
        onKeyDown={(e) => e.key === "Enter" && openEditor(id)}
        style={{
          height,
          width: NODE_WIDTH,
          borderRadius: visual.isTrigger ? "36px 14px 14px 36px" : "14px",
        }}
        className={cn(
          "relative grid cursor-pointer place-items-center border-2 bg-surface transition-colors",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
          BORDER_BY_STATUS[status],
          selected && "shadow-[0_0_0_4px_var(--accent-bg)] border-accent"
        )}
      >
        {/* Always rendered (even for triggers) so a drop still resolves to a
            real handle and checkConnection's reject-toast actually fires;
            triggers just hide it visually. */}
        <Handle
          type="target"
          position={Position.Left}
          className={cn(
            "!h-3 !w-3 !border-2 !border-[#8E98A8] !bg-surface",
            visual.isTrigger && "!opacity-0"
          )}
        />

        <Icon className={cn("h-8 w-8", COLOR_TEXT_CLASS[visual.color], status === "skipped" && "opacity-45")} />

        {status === "succeeded" && (
          <span className="absolute -right-2 -top-2 grid h-5 w-5 place-items-center rounded-full border-2 border-canvas bg-ok text-white">
            <Check className="h-3 w-3" />
          </span>
        )}
        {status === "failed" && (
          <span className="absolute -right-2 -top-2 grid h-5 w-5 place-items-center rounded-full border-2 border-canvas bg-err text-white">
            <AlertTriangle className="h-3 w-3" />
          </span>
        )}
        {status === "skipped" && (
          <span className="absolute -right-2 -top-2 grid h-5 w-5 place-items-center rounded-full border-2 border-canvas bg-[#9AA4B2] text-white">
            <SkipForward className="h-3 w-3" />
          </span>
        )}

        {outputs.map((h, i) => (
          <Handle
            key={h}
            type="source"
            position={Position.Right}
            id={h}
            style={{ top: handleTop(i, outputs.length, height) }}
            className="!h-3 !w-3 !border-2 !border-[#8E98A8] !bg-surface hover:!scale-125 hover:!border-accent hover:!bg-accent"
          />
        ))}
        {data.blockType === "switch" &&
          outputs.map((h, i) => (
            <span
              key={h}
              className="pointer-events-none absolute left-full ml-3 whitespace-nowrap text-[11px] text-ink-3"
              style={{ top: handleTop(i, outputs.length, height) - 8 }}
            >
              {h}
            </span>
          ))}
      </div>
      <div className="mt-2 w-[150px] text-center">
        <div className="text-[13px] font-semibold">{id}</div>
        <div className="mt-0.5 overflow-hidden text-ellipsis whitespace-nowrap text-[11px] text-ink-3">
          {subtitle}
        </div>
      </div>
    </div>
  );
});
