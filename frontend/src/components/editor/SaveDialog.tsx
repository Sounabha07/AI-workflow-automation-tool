import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { createPipeline, listPipelines, updatePipeline } from "@/api/pipelines";
import type { WorkflowDefinition } from "@/api/types";
import { ApiError } from "@/api/client";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const NAME_PATTERN = /^[a-z0-9_]+$/;

export function SaveDialog({
  open,
  onOpenChange,
  pipelineId,
  pipelineName,
  definition,
  runId,
  runCreatedAt,
  pipelineUpdatedAt,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pipelineId: string;
  pipelineName: string;
  definition: WorkflowDefinition;
  runId: string;
  runCreatedAt: string;
  pipelineUpdatedAt: string;
  onSaved: (pipelineId: string) => void;
}) {
  const queryClient = useQueryClient();
  const { data: pipelines = [] } = useQuery({ queryKey: ["pipelines"], queryFn: listPipelines });
  const [choice, setChoice] = useState<"update" | "new">("update");
  const [newName, setNewName] = useState("");
  const [nameError, setNameError] = useState("");

  useEffect(() => {
    if (!open) return;
    setChoice("update");
    let n = 2;
    const existing = new Set(pipelines.map((p) => p.name));
    while (existing.has(`${pipelineName}_v${n}`)) n++;
    setNewName(`${pipelineName}_v${n}`);
    setNameError("");
  }, [open, pipelineName, pipelines]);

  const isOlderRun = new Date(pipelineUpdatedAt).getTime() > new Date(runCreatedAt).getTime();

  const save = useMutation({
    mutationFn: async () => {
      if (choice === "update") {
        return updatePipeline(pipelineId, { definition });
      }
      const trimmed = newName.trim();
      if (!trimmed) throw { field: "Enter a name for the new workflow." };
      if (!NAME_PATTERN.test(trimmed)) {
        throw { field: "Use lowercase letters, numbers and underscores." };
      }
      if (pipelines.some((p) => p.name === trimmed)) {
        throw { field: "A workflow with this name already exists." };
      }
      return createPipeline(trimmed, definition);
    },
    onSuccess: (pipeline) => {
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
      toast.success(choice === "update" ? `Updated ${pipelineName}` : `Created ${pipeline.name}`);
      onOpenChange(false);
      onSaved(pipeline.id);
    },
    onError: (err: unknown) => {
      if (err && typeof err === "object" && "field" in err) {
        setNameError((err as { field: string }).field);
        return;
      }
      toast.error(err instanceof ApiError ? err.message : "Couldn't save this workflow");
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>Save your changes</DialogTitle>
        <DialogDescription>
          You edited the version of <b>{pipelineName}</b> that ran in run{" "}
          <span className="font-mono">{runId.slice(0, 8)}</span>.
        </DialogDescription>

        {isOlderRun && (
          <div className="mb-3 rounded-md bg-run-bg px-2.5 py-2 text-xs text-[#8C6108]">
            This workflow has been edited since this run. Updating it replaces those newer edits
            with this version.
          </div>
        )}

        <label
          onClick={() => setChoice("update")}
          className={`mb-2.5 flex cursor-pointer gap-2.5 rounded-[9px] border p-3 ${
            choice === "update" ? "border-accent shadow-[0_0_0_3px_var(--accent-bg)]" : "border-line-2"
          }`}
        >
          <input type="radio" name="saveopt" className="mt-0.5 accent-accent" checked={choice === "update"} readOnly />
          <div>
            <b className="block text-[13px] font-semibold">Update {pipelineName}</b>
            <span className="text-xs text-ink-3">Replace the current version with your edited copy.</span>
          </div>
        </label>

        <label
          onClick={() => setChoice("new")}
          className={`flex cursor-pointer gap-2.5 rounded-[9px] border p-3 ${
            choice === "new" ? "border-accent shadow-[0_0_0_3px_var(--accent-bg)]" : "border-line-2"
          }`}
        >
          <input type="radio" name="saveopt" className="mt-0.5 accent-accent" checked={choice === "new"} readOnly />
          <div className="flex-1">
            <b className="block text-[13px] font-semibold">Save as a new workflow</b>
            <span className="text-xs text-ink-3">Leave the current workflow as it is. The new one starts inactive.</span>
            <Input
              value={newName}
              onChange={(e) => {
                setNewName(e.target.value);
                setNameError("");
              }}
              onFocus={() => setChoice("new")}
              aria-label="New workflow name"
              className="mt-2"
            />
            {nameError && <div className="mt-1.5 text-xs text-err">{nameError}</div>}
          </div>
        </label>

        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending}>
            {choice === "update" ? "Update workflow" : "Create workflow"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
