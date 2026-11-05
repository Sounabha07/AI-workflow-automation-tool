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
  /** A tool connection (HTTP block -> agent's Tools handle): not a DAG edge. */
  tool?: boolean;
}

export type FlowNode = Node<BlockNodeData, "block">;
export type FlowEdge = Edge<StatusEdgeData, "status" | "tool">;

/** The agent's target handle that tool blocks connect to. */
export const TOOLS_HANDLE = "tools";

export function edgeId(source: string, target: string): string {
  return `${source}->${target}`;
}

export function toolEdge(toolId: string, agentId: string): FlowEdge {
  return {
    id: `${toolId}=>${agentId}`,
    source: toolId,
    target: agentId,
    sourceHandle: "main",
    targetHandle: TOOLS_HANDLE,
    type: "tool",
    data: { tool: true },
  };
}

export function isToolEdge(e: FlowEdge): boolean {
  return e.data?.tool === true;
}

/** Edges the scheduler sees: everything except tool connections. */
export function dagEdges(edges: FlowEdge[]): FlowEdge[] {
  return edges.filter((e) => !isToolEdge(e));
}

/** The agent a tool block belongs to, if it is one. */
export function toolOwner(edges: FlowEdge[], blockId: string): string | undefined {
  return edges.find((e) => isToolEdge(e) && e.source === blockId)?.target;
}

export function agentToolIds(config: Record<string, unknown>): string[] {
  return Array.isArray(config.tools) ? config.tools.filter((t): t is string => typeof t === "string") : [];
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

    if (block.type === "agent") {
      for (const toolId of agentToolIds(block.config ?? {})) {
        if (definition.blocks[toolId]) edges.push(toolEdge(toolId, blockId));
      }
    }

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
  const dag = dagEdges(edges);
  const toolEdges = edges.filter(isToolEdge);

  for (const node of nodes) {
    const depends_on = dag.filter((e) => e.target === node.id).map((e) => e.source);

    const outgoing = dag.filter((e) => e.source === node.id);
    const next: string[] | Record<string, string[]> =
      node.data.blockType === "switch"
        ? outgoing.reduce<Record<string, string[]>>((acc, e) => {
            const output = e.data?.output ?? e.sourceHandle ?? "fallback";
            (acc[output] ??= []).push(e.target);
            return acc;
          }, {})
        : outgoing.map((e) => e.target);

    // An agent's tools follow its tool connections, keeping config order.
    let config = node.data.config;
    if (node.data.blockType === "agent") {
      const connected = toolEdges.filter((e) => e.target === node.id).map((e) => e.source);
      const ordered = agentToolIds(config).filter((t) => connected.includes(t));
      config = { ...config, tools: [...ordered, ...connected.filter((t) => !ordered.includes(t))] };
    }

    blocks[node.id] = {
      type: node.data.blockType,
      config,
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
