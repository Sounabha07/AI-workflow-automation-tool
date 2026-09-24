import { useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import type { BlockSchemaResponse } from "@/api/types";
import type { FlowNode, FlowEdge } from "@/lib/definition";
import { InputPane, type BlockDataEntry } from "./InputPane";
import { ParametersPane } from "./ParametersPane";
import { OutputPane } from "./OutputPane";
import type { ViewMode } from "./DataView";

export interface BlockOutputInfo extends BlockDataEntry {
  error: import("@/api/types").BlockError | null;
  startedAt?: string | null;
  finishedAt?: string | null;
}

export function BlockEditor({
  node,
  nodes,
  edges,
  schema,
  blockData,
  stoppedAtBlockId,
  onClose,
  onTestStep,
  testing,
}: {
  node: FlowNode;
  nodes: FlowNode[];
  edges: FlowEdge[];
  schema: BlockSchemaResponse["schema"] | undefined;
  blockData: Record<string, BlockOutputInfo>;
  stoppedAtBlockId?: string;
  onClose: () => void;
  onTestStep: () => void;
  testing: boolean;
}) {
  const [inMode, setInMode] = useState<ViewMode>("schema");
  const [outMode, setOutMode] = useState<ViewMode>("json");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const current = blockData[node.id];
  const durationMs =
    current?.startedAt && current?.finishedAt
      ? new Date(current.finishedAt).getTime() - new Date(current.startedAt).getTime()
      : null;

  // Only the Input pane needs status+output; strip the rest of BlockOutputInfo.
  const inputData: Record<string, BlockDataEntry> = Object.fromEntries(
    Object.entries(blockData).map(([id, v]) => [id, { status: v.status, output: v.output }])
  );

  return (
    <div className="fixed inset-0 z-10 bg-[#18202C]/45 p-5" role="dialog" aria-label="Block editor">
      <div className="flex h-full flex-col">
        <div className="flex h-10 items-center">
          <button
            onClick={onClose}
            className="flex items-center gap-1.5 rounded-md border-0 bg-transparent px-2 py-1 text-white hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to canvas
          </button>
        </div>
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(380px,440px)_minmax(0,1fr)] overflow-hidden rounded-xl bg-panel">
          <InputPane currentBlockId={node.id} nodes={nodes} edges={edges} data={inputData} mode={inMode} onModeChange={setInMode} />
          <div className="flex min-h-0 min-w-0 flex-col border-x border-line bg-surface">
            <ParametersPane
              node={node}
              schema={schema}
              outputs={Object.fromEntries(Object.entries(inputData).map(([id, v]) => [id, v.output]))}
              onTestStep={onTestStep}
              testing={testing}
            />
          </div>
          <OutputPane
            blockId={node.id}
            status={current?.status ?? "idle"}
            output={current?.output ?? null}
            error={current?.error ?? null}
            durationMs={durationMs}
            stoppedAtBlockId={stoppedAtBlockId}
            mode={outMode}
            onModeChange={setOutMode}
          />
        </div>
      </div>
    </div>
  );
}
