import type { Edge, Node } from "@xyflow/react";
import type { BlockDefinition, WorkflowDefinition } from "@/api/types";

export interface BlockNodeData extends Record<string, unknown> {
  blockId: string;
  blockType: string;
  config: Record<string, unknown>;
  notes: string;
}

export interface StatusEdgeData extends Record<string, unknown> {
  /** The switch output this edge hangs off, or undefined for a plain block. */
  output?: string;
}

export type FlowNode = Node<BlockNodeData, "block">;
export type FlowEdge = Edge<StatusEdgeData, "status">;

export function edgeId(source: string, target: string): string {
  return `${source}->${target}`;
}

/** Converts the backend definition shape (A2) into React Flow nodes/edges. */
export function definitionToFlow(definition: WorkflowDefinition): {
  nodes: FlowNode[];
  edges: FlowEdge[];
} {
  const nodes: FlowNode[] = [];
  const edges: FlowEdge[] = [];

  for (const [blockId, block] of Object.entries(definition.blocks)) {
    nodes.push({
      id: blockId,
      type: "block",
      position: block.position ?? { x: 0, y: 0 },
      data: {
        blockId,
        blockType: block.type,
        config: block.config ?? {},
        notes: block.notes ?? "",
      },
    });

    if (Array.isArray(block.next)) {
      for (const target of block.next) {
        edges.push({
          id: edgeId(blockId, target),
          source: blockId,
          target,
          type: "status",
          data: {},
        });
      }
    } else {
      for (const [output, targets] of Object.entries(block.next ?? {})) {
        for (const target of targets) {
          edges.push({
            id: edgeId(blockId, target),
            source: blockId,
            target,
            sourceHandle: output,
            type: "status",
            data: { output },
          });
        }
      }
    }
  }

  return { nodes, edges };
}

/** Converts React Flow nodes/edges back into the backend definition shape. */
export function flowToDefinition(nodes: FlowNode[], edges: FlowEdge[]): WorkflowDefinition {
  const blocks: Record<string, BlockDefinition> = {};

  for (const node of nodes) {
    const depends_on = edges.filter((e) => e.target === node.id).map((e) => e.source);

    const outgoing = edges.filter((e) => e.source === node.id);
    const next: string[] | Record<string, string[]> =
      node.data.blockType === "switch"
        ? outgoing.reduce<Record<string, string[]>>((acc, e) => {
            const output = e.data?.output ?? e.sourceHandle ?? "fallback";
            (acc[output] ??= []).push(e.target);
            return acc;
          }, {})
        : outgoing.map((e) => e.target);

    blocks[node.id] = {
      type: node.data.blockType,
      config: node.data.config,
      depends_on,
      next,
      position: { x: node.position.x, y: node.position.y },
      notes: node.data.notes ?? "",
    };
  }

  return { blocks };
}

/** The next free `<type>_<n>` id, per B6's "block picker" rule. */
export function nextBlockId(existingIds: Iterable<string>, type: string): string {
  const ids = new Set(existingIds);
  let n = 1;
  while (ids.has(`${type}_${n}`)) n++;
  return `${type}_${n}`;
}
