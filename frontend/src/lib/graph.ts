import type { FlowEdge, FlowNode } from "./definition";
import { blockVisual } from "./blockVisuals";

/** True if `target` can already reach `source` — i.e. connecting source->target would close a loop. */
export function wouldCreateCycle(edges: FlowEdge[], source: string, target: string): boolean {
  const seen = new Set([target]);
  const queue = [target];
  while (queue.length) {
    const current = queue.shift()!;
    if (current === source) return true;
    for (const e of edges) {
      if (e.source === current && !seen.has(e.target)) {
        seen.add(e.target);
        queue.push(e.target);
      }
    }
  }
  return false;
}

export interface ConnectionCheck {
  ok: boolean;
  message?: string;
}

/** The B6 connection rules, checked in `onConnect` before an edge is added. */
export function checkConnection(
  nodes: FlowNode[],
  edges: FlowEdge[],
  source: string,
  target: string
): ConnectionCheck {
  if (source === target) {
    return { ok: false, message: "A block can't connect to itself" };
  }
  if (edges.some((e) => e.source === source && e.target === target)) {
    return { ok: false, message: "These blocks are already connected" };
  }
  const targetNode = nodes.find((n) => n.id === target);
  if (targetNode && blockVisual(targetNode.data.blockType).isTrigger) {
    return { ok: false, message: "Triggers start a workflow, so they have no input" };
  }
  if (wouldCreateCycle(edges, source, target)) {
    return { ok: false, message: "That connection would create a loop" };
  }
  return { ok: true };
}

/** Direct parents (depends_on) of a block. */
export function parentsOf(edges: FlowEdge[], blockId: string): string[] {
  return edges.filter((e) => e.target === blockId).map((e) => e.source);
}

/** Every block upstream of blockId (not including direct parents), following depends_on. */
export function earlierAncestorsOf(edges: FlowEdge[], blockId: string): string[] {
  const parents = parentsOf(edges, blockId);
  const seen = new Set([blockId, ...parents]);
  const queue = [...parents];
  const ancestors: string[] = [];
  while (queue.length) {
    const current = queue.shift()!;
    for (const p of parentsOf(edges, current)) {
      if (!seen.has(p)) {
        seen.add(p);
        ancestors.push(p);
        queue.push(p);
      }
    }
  }
  return ancestors;
}

/** All ancestors (parents + earlier), for the test-step ancestor seeding preview. */
export function allAncestorsOf(edges: FlowEdge[], blockId: string): string[] {
  const parents = parentsOf(edges, blockId);
  return [...parents, ...earlierAncestorsOf(edges, blockId)];
}
