import { PlugZap2 } from "lucide-react";
import { parentsOf, earlierAncestorsOf } from "@/lib/graph";
import { blockVisual, COLOR_BG_CLASS } from "@/lib/blockVisuals";
import { noDataText } from "@/lib/noDataText";
import { DataView, type ViewMode } from "./DataView";
import type { FlowEdge, FlowNode } from "@/lib/definition";
import type { NodeRuntimeStatus } from "@/store/editor";

export interface BlockDataEntry {
  status: NodeRuntimeStatus;
  output: Record<string, unknown> | null;
}

function Section({
  blockId,
  node,
  entry,
  mode,
}: {
  blockId: string;
  node: FlowNode | undefined;
  entry: BlockDataEntry | undefined;
  mode: ViewMode;
}) {
  const visual = blockVisual(node?.data.blockType ?? "");
  const Icon = visual.icon;
  const hasData = entry?.output != null;
  return (
    <div className="mb-3.5">
      <div className="mb-1.5 flex items-center gap-2 text-xs font-semibold text-ink-2">
        <span className={`grid h-[18px] w-[18px] place-items-center rounded text-white ${COLOR_BG_CLASS[visual.color]}`}>
          <Icon className="h-2.5 w-2.5" />
        </span>
        {blockId}
        {hasData && <span className="font-normal text-ink-3">1 item</span>}
      </div>
      {hasData ? (
        <DataView data={entry!.output} mode={mode} baseId={blockId} />
      ) : (
        <div className="text-xs text-ink-3">{noDataText(blockId, entry?.status ?? "idle")}</div>
      )}
    </div>
  );
}

export function InputPane({
  currentBlockId,
  nodes,
  edges,
  data,
  mode,
  onModeChange,
}: {
  currentBlockId: string;
  nodes: FlowNode[];
  edges: FlowEdge[];
  data: Record<string, BlockDataEntry>;
  mode: ViewMode;
  onModeChange: (mode: ViewMode) => void;
}) {
  const parents = parentsOf(edges, currentBlockId);
  const ancestors = earlierAncestorsOf(edges, currentBlockId);
  const nodeById = (id: string) => nodes.find((n) => n.id === id);

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <PaneHead mode={mode} onModeChange={onModeChange} />
      <div className="min-h-0 flex-1 overflow-auto p-4">
        {parents.length === 0 ? (
          <div className="grid h-full place-items-center px-6 text-center text-[13px] text-ink-3">
            <div>
              <PlugZap2 className="mx-auto mb-2 h-7 w-7" />
              No input. Nothing flows into this block.
            </div>
          </div>
        ) : (
          <>
            {parents.map((id) => (
              <Section key={id} blockId={id} node={nodeById(id)} entry={data[id]} mode={mode} />
            ))}
            {ancestors.length > 0 && (
              <>
                <div className="my-4 border-t border-line pt-2.5 text-[11px] text-ink-3">
                  Earlier in the workflow
                </div>
                {ancestors.map((id) => (
                  <Section key={id} blockId={id} node={nodeById(id)} entry={data[id]} mode={mode} />
                ))}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function PaneHead({ mode, onModeChange }: { mode: ViewMode; onModeChange: (m: ViewMode) => void }) {
  return (
    <div className="flex h-12 items-center gap-2 border-b border-line px-4">
      <h3 className="m-0 text-xs font-semibold text-ink-2">Input</h3>
      <span className="flex-1" />
      <ModeToggle mode={mode} onModeChange={onModeChange} />
    </div>
  );
}

export function ModeToggle({ mode, onModeChange }: { mode: ViewMode; onModeChange: (m: ViewMode) => void }) {
  return (
    <div className="flex overflow-hidden rounded-[7px] border border-line-2">
      {(["schema", "table", "json"] as ViewMode[]).map((m) => (
        <button
          key={m}
          onClick={() => onModeChange(m)}
          className={`border-0 bg-surface px-2.5 py-1 text-xs capitalize text-ink-2 ${mode === m ? "bg-ink text-white" : ""}`}
        >
          {m}
        </button>
      ))}
    </div>
  );
}
