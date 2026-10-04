import { useReactFlow } from "@xyflow/react";
import { toast } from "sonner";
import { nextBlockId, type FlowNode } from "@/lib/definition";
import { blockVisual } from "@/lib/blockVisuals";
import { useEditorStore } from "@/store/editor";
import { useBlockSchemas, schemaFor } from "./useBlockSchemas";

const clone = <T,>(v: T): T => (v === undefined ? v : JSON.parse(JSON.stringify(v)));

/** Adds a block at a screen position, with the schema's field defaults, id
 * `<type>_<n>` (first free n), and marks the editor dirty (B6). A workflow
 * has exactly one trigger, so adding a trigger replaces the existing one in
 * place, keeping its outgoing connections. */
export function useAddBlock() {
  const { screenToFlowPosition } = useReactFlow();
  const { data: schemas } = useBlockSchemas();
  const nodes = useEditorStore((s) => s.nodes);
  const setNodes = useEditorStore((s) => s.setNodes);
  const setEdges = useEditorStore((s) => s.setEdges);
  const setBlockState = useEditorStore((s) => s.setBlockState);
  const markDirty = useEditorStore((s) => s.markDirty);

  return function addBlock(type: string, screenPos: { x: number; y: number }) {
    const schema = schemaFor(schemas, type);
    const id = nextBlockId(nodes.map((n) => n.id), type);
    const flowPos = screenToFlowPosition(screenPos);

    const config: Record<string, unknown> = {};
    for (const field of schema?.fields ?? []) {
      if (field.default !== undefined) config[field.name] = clone(field.default);
    }

    const oldTrigger = blockVisual(type).isTrigger
      ? nodes.find((n) => blockVisual(n.data.blockType).isTrigger)
      : undefined;

    const node: FlowNode = {
      id,
      type: "block",
      position: oldTrigger ? oldTrigger.position : { x: flowPos.x - 44, y: flowPos.y - 44 },
      data: { blockId: id, blockType: type, config, notes: "" },
    };

    if (oldTrigger) {
      setNodes((ns) => [...ns.filter((n) => n.id !== oldTrigger.id), node]);
      setEdges((es) =>
        es
          .filter((e) => e.target !== oldTrigger.id)
          .map((e) => (e.source === oldTrigger.id ? { ...e, id: `${id}->${e.target}`, source: id } : e))
      );
    } else {
      setNodes((ns) => [...ns, node]);
    }
    setBlockState(id, { status: "idle", output: null, error: null, retryCount: 0 });
    markDirty();
    toast(
      oldTrigger
        ? `Replaced ${oldTrigger.id} with ${id}: a workflow has one trigger.`
        : `Added ${id}. Double-click it to configure.`
    );
    return id;
  };
}
