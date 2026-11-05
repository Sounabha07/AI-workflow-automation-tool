import { create } from "zustand";
import type {
  AgentStepEvent,
  BlockError,
  BlockExecutionStatus,
  BlockStatusEvent,
  RunStatus,
  RunStatusEvent,
} from "@/api/types";
import { agentToolIds, isToolEdge, toolEdge, type FlowEdge, type FlowNode } from "@/lib/definition";
import { renameReferences } from "@/lib/expressions";

export type NodeRuntimeStatus = BlockExecutionStatus | "idle" | "not_run";

export interface BlockRuntimeState {
  status: NodeRuntimeStatus;
  output: Record<string, unknown> | null;
  error: BlockError | null;
  retryCount: number;
  startedAt?: string | null;
  finishedAt?: string | null;
  /** Wait for Input blocks: where to POST to resume, and when it times out. */
  resumeUrl?: string | null;
  waitDeadline?: string | null;
}

export type EditorMode = "edit" | "run";

const IDLE_STATE: BlockRuntimeState = { status: "idle", output: null, error: null, retryCount: 0 };

interface EditorStore {
  pipelineId: string | null;
  pipelineName: string;
  nodes: FlowNode[];
  edges: FlowEdge[];
  dirty: boolean;
  mode: EditorMode;
  viewingRunId: string | null;
  /** The run currently subscribed to over WS (a live run, whether started here or being watched in run view). */
  activeRunId: string | null;
  activeRunStatus: RunStatus | null;
  blockStates: Record<string, BlockRuntimeState>;
  /** Live "calling <tool>…" text per agent block, from agent.step events. */
  agentActivity: Record<string, string | null>;
  openBlockId: string | null;

  setPipelineMeta: (id: string, name: string) => void;
  setGraph: (nodes: FlowNode[], edges: FlowEdge[]) => void;
  setNodes: (updater: FlowNode[] | ((nodes: FlowNode[]) => FlowNode[])) => void;
  setEdges: (updater: FlowEdge[] | ((edges: FlowEdge[]) => FlowEdge[])) => void;
  updateNodeConfig: (blockId: string, updater: (config: Record<string, unknown>) => Record<string, unknown>) => void;
  updateNodeNotes: (blockId: string, notes: string) => void;
  renameNode: (oldId: string, newId: string) => void;
  removeEdgesForOutputs: (blockId: string, removedOutputs: string[]) => void;
  markDirty: () => void;
  clearDirty: () => void;
  setMode: (mode: EditorMode) => void;
  setViewingRunId: (id: string | null) => void;
  setActiveRun: (id: string | null) => void;
  resetBlockStates: (states?: Record<string, BlockRuntimeState>) => void;
  setBlockState: (blockId: string, state: Partial<BlockRuntimeState>) => void;
  applyBlockStatusEvent: (event: BlockStatusEvent) => void;
  applyRunStatusEvent: (event: RunStatusEvent) => void;
  applyAgentStepEvent: (event: AgentStepEvent) => void;
  /** Wires toolId to agentId's Tools handle: adds it to agent.tools, no depends_on. */
  connectTool: (toolId: string, agentId: string) => void;
  /** Drops a removed tool connection from its agent's config.tools. */
  disconnectTools: (removed: FlowEdge[]) => void;
  setOpenBlockId: (id: string | null) => void;
  /** EditorPage's "Run workflow" flow, registered so a trigger node can start it too. */
  runWorkflow: (() => void) | null;
  setRunWorkflow: (fn: (() => void) | null) => void;
  reset: () => void;
}

export const useEditorStore = create<EditorStore>((set, get) => ({
  pipelineId: null,
  pipelineName: "",
  nodes: [],
  edges: [],
  dirty: false,
  mode: "edit",
  viewingRunId: null,
  activeRunId: null,
  activeRunStatus: null,
  blockStates: {},
  agentActivity: {},
  openBlockId: null,
  runWorkflow: null,

  setPipelineMeta: (id, name) => set({ pipelineId: id, pipelineName: name }),

  setGraph: (nodes, edges) => set({ nodes, edges }),

  setNodes: (updater) =>
    set((s) => ({ nodes: typeof updater === "function" ? updater(s.nodes) : updater })),

  setEdges: (updater) =>
    set((s) => ({ edges: typeof updater === "function" ? updater(s.edges) : updater })),

  updateNodeConfig: (blockId, updater) =>
    set((s) => ({
      nodes: s.nodes.map((n) =>
        n.id === blockId ? { ...n, data: { ...n.data, config: updater(n.data.config) } } : n
      ),
    })),

  updateNodeNotes: (blockId, notes) =>
    set((s) => ({
      nodes: s.nodes.map((n) => (n.id === blockId ? { ...n, data: { ...n.data, notes } } : n)),
    })),

  renameNode: (oldId, newId) =>
    set((s) => ({
      // Rewrite {{ oldId.<path> }} references in every block's config, not
      // just the renamed one, then rename the node/edges themselves.
      nodes: s.nodes.map((n) => {
        let config = renameReferences(n.data.config, oldId, newId);
        if (n.data.blockType === "agent" && agentToolIds(config).includes(oldId)) {
          config = { ...config, tools: agentToolIds(config).map((t) => (t === oldId ? newId : t)) };
        }
        if (n.id === oldId) return { ...n, id: newId, data: { ...n.data, blockId: newId, config } };
        return config === n.data.config ? n : { ...n, data: { ...n.data, config } };
      }),
      edges: s.edges.map((e) => {
        if (e.source !== oldId && e.target !== oldId) return e;
        const source = e.source === oldId ? newId : e.source;
        const target = e.target === oldId ? newId : e.target;
        if (isToolEdge(e)) return toolEdge(source, target);
        return { ...e, id: `${source}->${target}`, source, target };
      }),
      openBlockId: s.openBlockId === oldId ? newId : s.openBlockId,
      blockStates: Object.fromEntries(
        Object.entries(s.blockStates).map(([k, v]) => [k === oldId ? newId : k, v])
      ),
    })),

  removeEdgesForOutputs: (blockId, removedOutputs) =>
    set((s) => ({
      edges: s.edges.filter(
        (e) => !(e.source === blockId && e.data?.output && removedOutputs.includes(e.data.output))
      ),
    })),

  markDirty: () => set({ dirty: true }),
  clearDirty: () => set({ dirty: false }),

  setMode: (mode) => set({ mode }),
  setViewingRunId: (id) => set({ viewingRunId: id }),
  setActiveRun: (id) => set({ activeRunId: id, activeRunStatus: id ? "running" : null }),

  resetBlockStates: (states) =>
    set((s) => ({
      blockStates:
        states ??
        Object.fromEntries(s.nodes.map((n) => [n.id, IDLE_STATE])),
    })),

  setBlockState: (blockId, patch) =>
    set((s) => ({
      blockStates: {
        ...s.blockStates,
        [blockId]: { ...(s.blockStates[blockId] ?? IDLE_STATE), ...patch },
      },
    })),

  applyBlockStatusEvent: (event) =>
    set((s) => {
      if (event.run_id !== s.activeRunId) return s;
      const prev = s.blockStates[event.block_id];
      return {
        blockStates: {
          ...s.blockStates,
          [event.block_id]: {
            status: event.status,
            output: prev?.output ?? null,
            error: event.error,
            retryCount: event.retry_count,
            resumeUrl: event.resume_url ?? prev?.resumeUrl,
            waitDeadline: event.wait_deadline ?? prev?.waitDeadline,
          },
        },
      };
    }),

  applyRunStatusEvent: (event) => {
    if (event.run_id !== get().activeRunId) return;
    set((s) => ({
      activeRunStatus: event.status,
      agentActivity: event.status === "running" ? s.agentActivity : {},
    }));
  },

  applyAgentStepEvent: (event) =>
    set((s) => {
      if (event.run_id !== s.activeRunId) return s;
      const text =
        event.kind === "tool" && event.status === "started"
          ? `calling ${event.tool_name}…`
          : event.kind === "model" && event.status === "completed"
            ? `step ${event.step_index + 1}`
            : event.kind === "tool"
              ? `${event.tool_name} ${event.status === "failed" ? "failed" : "done"}`
              : s.agentActivity[event.block_id] ?? null;
      return { agentActivity: { ...s.agentActivity, [event.block_id]: text } };
    }),

  connectTool: (toolId, agentId) =>
    set((s) => ({
      nodes: s.nodes.map((n) =>
        n.id === agentId
          ? {
              ...n,
              data: {
                ...n.data,
                config: { ...n.data.config, tools: [...agentToolIds(n.data.config).filter((t) => t !== toolId), toolId] },
              },
            }
          : n
      ),
      edges: [...s.edges.filter((e) => !(isToolEdge(e) && e.source === toolId)), toolEdge(toolId, agentId)],
    })),

  disconnectTools: (removed) =>
    set((s) => {
      const gone = removed.filter(isToolEdge);
      if (!gone.length) return s;
      return {
        nodes: s.nodes.map((n) => {
          const drop = gone.filter((e) => e.target === n.id).map((e) => e.source);
          if (!drop.length) return n;
          return {
            ...n,
            data: { ...n.data, config: { ...n.data.config, tools: agentToolIds(n.data.config).filter((t) => !drop.includes(t)) } },
          };
        }),
      };
    }),

  setOpenBlockId: (id) => set({ openBlockId: id }),
  setRunWorkflow: (fn) => set({ runWorkflow: fn }),

  reset: () =>
    set({
      pipelineId: null,
      pipelineName: "",
      nodes: [],
      edges: [],
      dirty: false,
      mode: "edit",
      viewingRunId: null,
      activeRunId: null,
      activeRunStatus: null,
      blockStates: {},
      agentActivity: {},
      openBlockId: null,
    }),
}));
