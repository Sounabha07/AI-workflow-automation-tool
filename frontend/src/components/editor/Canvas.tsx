import { useCallback, type RefObject } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { toast } from "sonner";
import type { RunDetailResponse } from "@/api/types";
import { BlockNode } from "./BlockNode";
import { StatusEdge } from "./StatusEdge";
import { RunBar } from "./RunBar";
import { RunBanner } from "./RunBanner";
import { edgeId, type FlowEdge, type FlowNode } from "@/lib/definition";
import { checkConnection } from "@/lib/graph";
import { useAddBlock } from "@/hooks/useAddBlock";
import { useEditorStore } from "@/store/editor";

const nodeTypes = { block: BlockNode };
const edgeTypes = { status: StatusEdge };

export function Canvas({
  wrapperRef,
  viewingRun,
  onRun,
  running,
  onBackToHistory,
  onOpenCurrentVersion,
}: {
  wrapperRef: RefObject<HTMLDivElement | null>;
  viewingRun: RunDetailResponse | null;
  onRun: () => void;
  running: boolean;
  onBackToHistory: () => void;
  onOpenCurrentVersion: () => void;
}) {
  const nodes = useEditorStore((s) => s.nodes);
  const edges = useEditorStore((s) => s.edges);
  const setNodes = useEditorStore((s) => s.setNodes);
  const setEdges = useEditorStore((s) => s.setEdges);
  const markDirty = useEditorStore((s) => s.markDirty);
  const activeRunId = useEditorStore((s) => s.activeRunId);
  const addBlock = useAddBlock();

  // The canvas stays editable in run view too (B6): editing marks it dirty,
  // and Save there opens SaveDialog instead of saving in place.
  const displayRunId = viewingRun?.id ?? activeRunId;

  const onNodesChange = useCallback(
    (changes: NodeChange<FlowNode>[]) => {
      setNodes((ns) => applyNodeChanges(changes, ns));
      if (changes.some((c) => c.type === "remove" || (c.type === "position" && c.dragging === false))) {
        markDirty();
      }
    },
    [setNodes, markDirty]
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange<FlowEdge>[]) => {
      setEdges((es) => applyEdgeChanges(changes, es));
      if (changes.some((c) => c.type === "remove")) markDirty();
    },
    [setEdges, markDirty]
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      const check = checkConnection(nodes, edges, connection.source, connection.target);
      if (!check.ok) {
        toast.error(check.message);
        return;
      }
      const sourceNode = nodes.find((n) => n.id === connection.source);
      const output = sourceNode?.data.blockType === "switch" ? connection.sourceHandle ?? undefined : undefined;
      setEdges((es) => [
        ...es,
        {
          id: edgeId(connection.source, connection.target),
          source: connection.source,
          target: connection.target,
          sourceHandle: connection.sourceHandle,
          type: "status",
          data: { output },
        },
      ]);
      markDirty();
    },
    [nodes, edges, setEdges, markDirty]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      const type = e.dataTransfer.getData("application/x-block-type");
      if (!type) return;
      e.preventDefault();
      addBlock(type, { x: e.clientX, y: e.clientY });
    },
    [addBlock]
  );

  const onDragOver = useCallback((e: React.DragEvent) => {
    if (e.dataTransfer.types.includes("application/x-block-type")) e.preventDefault();
  }, []);

  return (
    <div
      ref={wrapperRef as RefObject<HTMLDivElement>}
      className="relative h-full"
      onDrop={onDrop}
      onDragOver={onDragOver}
    >
      {viewingRun && (
        <RunBanner run={viewingRun} onBack={onBackToHistory} onOpenCurrent={onOpenCurrentVersion} />
      )}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        deleteKeyCode={["Backspace", "Delete"]}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} color="#C9D0DA" gap={20} />
        <Controls position="bottom-left" showInteractive={false} />
      </ReactFlow>
      <RunBar runId={displayRunId} onRun={onRun} running={running} />
    </div>
  );
}
