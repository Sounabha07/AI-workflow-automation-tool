import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { ReactFlowProvider } from "@xyflow/react";
import { toast } from "sonner";
import { getLatestOutputs, getPipeline, updatePipeline } from "@/api/pipelines";
import { getRun, getRunBlock, getRunBlocks, testStep, triggerRun } from "@/api/runs";
import { ApiError } from "@/api/client";
import type { RunEvent, WorkflowDefinition } from "@/api/types";
import { definitionToFlow, flowToDefinition } from "@/lib/definition";
import { useEditorStore, type BlockRuntimeState } from "@/store/editor";
import { applyPipelineActive } from "@/lib/pipelineCache";
import { useRunEvents } from "@/hooks/useRunEvents";
import { useBlockSchemas, schemaFor } from "@/hooks/useBlockSchemas";
import { useSetPipelineActive } from "@/hooks/useSetPipelineActive";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { BlockPicker } from "@/components/editor/BlockPicker";
import { Canvas } from "@/components/editor/Canvas";
import { BlockEditor } from "@/components/ndv/BlockEditor";
import { SaveDialog } from "@/components/editor/SaveDialog";
import { WorkflowNameInput } from "@/components/editor/WorkflowNameInput";
import { RunInputDialog, type InputFieldDef } from "@/components/editor/RunInputDialog";

function EditorPageInner() {
  const { id, runId } = useParams<{ id: string; runId?: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const wrapperRef = useRef<HTMLDivElement>(null);
  const loadedKeyRef = useRef<string>("");

  const nodes = useEditorStore((s) => s.nodes);
  const edges = useEditorStore((s) => s.edges);
  const dirty = useEditorStore((s) => s.dirty);
  const mode = useEditorStore((s) => s.mode);
  const pipelineId = useEditorStore((s) => s.pipelineId);
  const pipelineName = useEditorStore((s) => s.pipelineName);
  const viewingRunId = useEditorStore((s) => s.viewingRunId);
  const activeRunId = useEditorStore((s) => s.activeRunId);
  const openBlockId = useEditorStore((s) => s.openBlockId);
  const blockStates = useEditorStore((s) => s.blockStates);
  const setGraph = useEditorStore((s) => s.setGraph);
  const setPipelineMeta = useEditorStore((s) => s.setPipelineMeta);
  const setMode = useEditorStore((s) => s.setMode);
  const setViewingRunId = useEditorStore((s) => s.setViewingRunId);
  const setActiveRun = useEditorStore((s) => s.setActiveRun);
  const resetBlockStates = useEditorStore((s) => s.resetBlockStates);
  const setBlockState = useEditorStore((s) => s.setBlockState);
  const applyBlockStatusEvent = useEditorStore((s) => s.applyBlockStatusEvent);
  const applyRunStatusEvent = useEditorStore((s) => s.applyRunStatusEvent);
  const setOpenBlockId = useEditorStore((s) => s.setOpenBlockId);
  const clearDirty = useEditorStore((s) => s.clearDirty);

  const { data: schemas } = useBlockSchemas();

  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [pendingAfterSave, setPendingAfterSave] = useState<"run" | null>(null);
  const [inputDialog, setInputDialog] = useState<{ purpose: "run" | "test"; blockId?: string } | null>(null);
  const [testingBlockId, setTestingBlockId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  // ---- data loading -------------------------------------------------

  const pipelineQuery = useQuery({
    queryKey: ["pipeline", id],
    queryFn: () => getPipeline(id!),
    enabled: !!id && !runId,
  });
  const latestOutputsQuery = useQuery({
    queryKey: ["latestOutputs", id],
    queryFn: () => getLatestOutputs(id!),
    enabled: !!id && !runId,
  });
  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId!),
    enabled: !!runId,
  });
  const runBlocksQuery = useQuery({
    queryKey: ["runBlocks", runId],
    queryFn: () => getRunBlocks(runId!),
    enabled: !!runId,
  });

  useEffect(() => {
    if (runId) return;
    const key = `edit:${id}`;
    if (loadedKeyRef.current === key || !pipelineQuery.data) return;
    const { nodes: n, edges: e } = definitionToFlow(pipelineQuery.data.definition);
    setGraph(n, e);
    setPipelineMeta(pipelineQuery.data.id, pipelineQuery.data.name);
    setMode("edit");
    setViewingRunId(null);
    setActiveRun(null);
    resetBlockStates(
      Object.fromEntries(n.map((node) => [node.id, { status: "idle", output: null, error: null, retryCount: 0 } as BlockRuntimeState]))
    );
    clearDirty();
    loadedKeyRef.current = key;
  }, [id, runId, pipelineQuery.data, setGraph, setPipelineMeta, setMode, setViewingRunId, setActiveRun, resetBlockStates, clearDirty]);

  useEffect(() => {
    if (!runId) return;
    const key = `run:${runId}`;
    if (loadedKeyRef.current === key || !runQuery.data || !runBlocksQuery.data) return;
    const { nodes: n, edges: e } = definitionToFlow(runQuery.data.pipeline_snapshot);
    setGraph(n, e);
    setPipelineMeta(runQuery.data.pipeline_id, runQuery.data.pipeline_name);
    setMode("run");
    setViewingRunId(runId);
    const byId = Object.fromEntries(runBlocksQuery.data.map((b) => [b.block_id, b]));
    const states: Record<string, BlockRuntimeState> = {};
    for (const node of n) {
      const b = byId[node.id];
      if (!b) {
        states[node.id] = { status: "not_run", output: null, error: null, retryCount: 0 };
        continue;
      }
      const status = b.status === "pending" && runQuery.data!.status === "failed" ? "not_run" : b.status;
      states[node.id] = {
        status,
        output: b.output,
        error: b.error,
        retryCount: b.retry_count,
        startedAt: b.started_at,
        finishedAt: b.finished_at,
      };
    }
    resetBlockStates(states);
    setActiveRun(runQuery.data.status === "running" ? runId : null);
    clearDirty();
    loadedKeyRef.current = key;
  }, [runId, runQuery.data, runBlocksQuery.data, setGraph, setPipelineMeta, setMode, setViewingRunId, setActiveRun, resetBlockStates, clearDirty]);

  // ---- live updates ---------------------------------------------------

  const onRunEvent = useCallback(
    (event: RunEvent) => {
      if (event.type === "block_status") {
        applyBlockStatusEvent(event);
        if (event.status === "succeeded" || event.status === "failed") {
          getRunBlock(event.run_id, event.block_id).then((full) => {
            setBlockState(event.block_id, {
              status: full.status,
              output: full.output,
              error: full.error,
              retryCount: full.retry_count,
              startedAt: full.started_at,
              finishedAt: full.finished_at,
            });
            setTestingBlockId((cur) => (cur === event.block_id ? null : cur));
          });
        }
      } else {
        applyRunStatusEvent(event);
        if (event.status !== "running") {
          setRunning(false);
          queryClient.invalidateQueries({ queryKey: ["pipelines"] });
          queryClient.invalidateQueries({ queryKey: ["runs"] });
          queryClient.invalidateQueries({ queryKey: ["runBlocks", event.run_id] });
          queryClient.invalidateQueries({ queryKey: ["run", event.run_id] });
          if (!runId) queryClient.invalidateQueries({ queryKey: ["latestOutputs", id] });
        }
      }
    },
    [applyBlockStatusEvent, applyRunStatusEvent, setBlockState, queryClient, id, runId]
  );

  useRunEvents(activeRunId, onRunEvent);

  // Let a trigger node start the same flow as the "Run workflow" button. The
  // ref keeps the registered function stable while always calling the latest
  // handleRunWorkflow (which closes over the current nodes, edges and dirty).
  const runWorkflowRef = useRef<() => void>(() => {});
  runWorkflowRef.current = () => handleRunWorkflow();
  const setRunWorkflow = useEditorStore((s) => s.setRunWorkflow);
  useEffect(() => {
    setRunWorkflow(() => runWorkflowRef.current());
    return () => setRunWorkflow(null);
  }, [setRunWorkflow]);

  // Warn on navigation away with unsaved changes (B6).
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  function confirmLeave(): boolean {
    return !dirty || window.confirm("You have unsaved changes. Leave without saving?");
  }

  // ---- save -------------------------------------------------------------

  const saveMutation = useMutation({
    mutationFn: (definition: WorkflowDefinition) => updatePipeline(pipelineId!, { definition }),
    onSuccess: () => {
      clearDirty();
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
      queryClient.invalidateQueries({ queryKey: ["pipeline", pipelineId] });
      toast.success("Saved");
    },
    onError: (err) => reportSaveError(err),
  });

  function reportSaveError(err: unknown) {
    if (err instanceof ApiError && err.problems?.length) {
      toast.error("Invalid workflow", { description: err.problems.join("\n") });
    } else {
      toast.error(err instanceof ApiError ? err.message : "Couldn't save this workflow");
    }
  }

  const activeMutation = useSetPipelineActive();

  const isActive = mode === "edit" ? pipelineQuery.data?.is_active ?? false : false;

  const handleSaveClick = () => {
    if (!dirty) {
      toast("No changes to save");
      return;
    }
    if (mode === "run") {
      setSaveDialogOpen(true);
      return;
    }
    saveMutation.mutate(flowToDefinition(nodes, edges));
  };

  // ---- run workflow -------------------------------------------------------

  async function startRun(targetPipelineId: string, definition: WorkflowDefinition, inputData: Record<string, unknown> = {}) {
    setRunning(true);
    try {
      const { run_id, pipeline_is_active } = await triggerRun(targetPipelineId, inputData);
      // POST /runs switches the workflow on; show it without waiting for a refetch.
      applyPipelineActive(queryClient, targetPipelineId, pipeline_is_active);
      setActiveRun(run_id);
      resetBlockStates(
        Object.fromEntries(
          Object.keys(definition.blocks).map((bid) => [bid, { status: "ready", output: null, error: null, retryCount: 0 } as BlockRuntimeState])
        )
      );
    } catch (err) {
      setRunning(false);
      toast.error(err instanceof ApiError ? err.message : "Couldn't start the run");
    }
  }

  function inputBlockFields(definition: WorkflowDefinition): InputFieldDef[] | null {
    const inputBlock = Object.values(definition.blocks).find((b) => b.type === "input_block");
    if (!inputBlock) return null;
    const fields = Array.isArray(inputBlock.config.fields) ? (inputBlock.config.fields as InputFieldDef[]) : [];
    return fields;
  }

  function handleRunWorkflow() {
    if (running) return;
    const definition = flowToDefinition(nodes, edges);

    if (mode === "run") {
      if (dirty) {
        setPendingAfterSave("run");
        setSaveDialogOpen(true);
        return;
      }
      const fields = inputBlockFields(definition);
      if (fields) {
        setInputDialog({ purpose: "run" });
        return;
      }
      startRun(pipelineId!, definition);
      return;
    }

    // edit mode
    const afterSave = () => {
      const fields = inputBlockFields(definition);
      if (fields) {
        setInputDialog({ purpose: "run" });
        return;
      }
      startRun(pipelineId!, definition);
    };
    if (dirty) {
      saveMutation.mutate(definition, { onSuccess: afterSave });
      return;
    }
    afterSave();
  }

  // After Save-as-new/Update from run view, optionally continue with a run.
  useEffect(() => {
    if (pendingAfterSave === "run" && mode === "edit" && loadedKeyRef.current === `edit:${id}`) {
      setPendingAfterSave(null);
      const definition = flowToDefinition(useEditorStore.getState().nodes, useEditorStore.getState().edges);
      const fields = inputBlockFields(definition);
      if (fields) setInputDialog({ purpose: "run" });
      else startRun(id!, definition);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingAfterSave, mode, id]);

  // ---- test step -------------------------------------------------------

  async function runTestStep(blockId: string, inputData: Record<string, unknown>) {
    setTestingBlockId(blockId);
    setBlockState(blockId, { status: "running", output: null, error: null });
    try {
      const definition = flowToDefinition(nodes, edges);
      const { run_id } = await testStep({ pipeline_id: pipelineId!, block_id: blockId, definition, input_data: inputData });
      setActiveRun(run_id);
    } catch (err) {
      setTestingBlockId(null);
      setBlockState(blockId, { status: "idle" });
      toast.error(err instanceof ApiError ? err.message : "Couldn't test this block");
    }
  }

  function handleTestStep(blockId: string) {
    const definition = flowToDefinition(nodes, edges);
    if (definition.blocks[blockId]?.type === "input_block") {
      setInputDialog({ purpose: "test", blockId });
      return;
    }
    runTestStep(blockId, {});
  }

  // ---- render data --------------------------------------------------------

  const currentNode = nodes.find((n) => n.id === openBlockId);
  const schema = currentNode ? schemaFor(schemas, currentNode.data.blockType) : undefined;

  const hasLiveData = !!activeRunId || mode === "run";
  const blockData = Object.fromEntries(
    nodes.map((n) => {
      if (hasLiveData) {
        const st = blockStates[n.id];
        return [
          n.id,
          {
            status: st?.status ?? "idle",
            output: st?.output ?? null,
            error: st?.error ?? null,
            startedAt: st?.startedAt,
            finishedAt: st?.finishedAt,
          },
        ];
      }
      const lo = latestOutputsQuery.data?.[n.id];
      if (!lo) return [n.id, { status: "idle" as const, output: null, error: null }];
      return [n.id, { status: lo.status, output: lo.output, error: lo.error, finishedAt: lo.finished_at }];
    })
  );

  const viewingRun = mode === "run" ? runQuery.data ?? null : null;

  const breadcrumb = mode === "run" ? "History" : "Workflows";
  const breadcrumbTarget = mode === "run" ? "/history" : "/";

  return (
    <div className="grid h-full min-h-0 grid-rows-[48px_auto_1fr]">
      <div className="flex items-center gap-3 border-b border-line bg-surface px-4">
        <button
          onClick={() => confirmLeave() && navigate(breadcrumbTarget)}
          className="border-0 bg-transparent p-0 text-ink-3 hover:text-ink"
        >
          {breadcrumb}
        </button>
        <span className="text-ink-3">/</span>
        {mode === "edit" && pipelineId ? (
          <WorkflowNameInput pipelineId={pipelineId} name={pipelineName} />
        ) : (
          <span className="font-semibold">{pipelineName}</span>
        )}
        {dirty && (
          <span className="flex items-center gap-1 text-xs text-[#8C6108]">
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            Unsaved changes
          </span>
        )}
        <span className="flex-1" />
        {mode === "edit" && (
          <span className="flex items-center gap-2 text-xs text-ink-2">
            {isActive ? "Active" : "Inactive"}
            <Switch checked={isActive} onCheckedChange={(v) => activeMutation.mutate({ id: pipelineId!, is_active: v })} aria-label="Active" />
          </span>
        )}
        <Button variant="primary" onClick={handleSaveClick} disabled={saveMutation.isPending}>
          Save
        </Button>
      </div>

      <BlockPicker wrapperRef={wrapperRef} />

      <Canvas
        wrapperRef={wrapperRef}
        viewingRun={viewingRun}
        onRun={handleRunWorkflow}
        running={running}
        onBackToHistory={() => confirmLeave() && navigate("/history")}
        onOpenCurrentVersion={() => confirmLeave() && navigate(`/workflows/${pipelineId}`)}
      />

      {currentNode && (
        <BlockEditor
          node={currentNode}
          nodes={nodes}
          edges={edges}
          schema={schema}
          blockData={blockData}
          stoppedAtBlockId={viewingRun?.error_summary?.block_id}
          onClose={() => setOpenBlockId(null)}
          onTestStep={() => handleTestStep(currentNode.id)}
          testing={testingBlockId === currentNode.id}
        />
      )}

      {saveDialogOpen && viewingRunId && runQuery.data && (
        <SaveDialog
          open={saveDialogOpen}
          onOpenChange={(open) => {
            setSaveDialogOpen(open);
            if (!open) setPendingAfterSave(null);
          }}
          pipelineId={pipelineId!}
          pipelineName={pipelineName}
          definition={flowToDefinition(nodes, edges)}
          runId={viewingRunId}
          runCreatedAt={runQuery.data.created_at}
          pipelineUpdatedAt={runQuery.data.pipeline_updated_at}
          onSaved={(newId) => navigate(`/workflows/${newId}`)}
        />
      )}

      {inputDialog && (
        <RunInputDialog
          open={!!inputDialog}
          onOpenChange={(open) => !open && setInputDialog(null)}
          fields={inputBlockFields(flowToDefinition(nodes, edges)) ?? []}
          onSubmit={(values) => {
            if (inputDialog.purpose === "test" && inputDialog.blockId) {
              runTestStep(inputDialog.blockId, values);
            } else {
              startRun(pipelineId!, flowToDefinition(nodes, edges), values);
            }
          }}
        />
      )}
    </div>
  );
}

export function EditorPage() {
  return (
    <ReactFlowProvider>
      <EditorPageInner />
    </ReactFlowProvider>
  );
}
