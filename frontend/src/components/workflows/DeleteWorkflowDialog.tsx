import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { deletePipeline } from "@/api/pipelines";
import { ApiError } from "@/api/client";
import type { PipelineListItem } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { removePipelineFromCache } from "@/lib/pipelineCache";

export function DeleteWorkflowDialog({
  pipeline,
  onClose,
}: {
  pipeline: PipelineListItem | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();

  const remove = useMutation({
    mutationFn: (p: PipelineListItem) => deletePipeline(p.id),
    onSuccess: (_data, p) => {
      removePipelineFromCache(queryClient, p.id);
      toast.success(`${p.name} deleted`);
      onClose();
    },
    onError: (err, p) => {
      onClose();
      if (err instanceof ApiError && err.status === 409) {
        // Expected: runs reference the pipeline (ON DELETE RESTRICT).
        toast.error(`Can't delete ${p.name}, it has run history. Delete its runs first, or keep it.`);
        return;
      }
      toast.error(err instanceof ApiError ? `Couldn't delete ${p.name}: ${err.message}` : `Couldn't delete ${p.name}`);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["pipelines"] }),
  });

  return (
    <Dialog open={!!pipeline} onOpenChange={(open) => !open && !remove.isPending && onClose()}>
      <DialogContent hideClose>
        <DialogTitle>Delete {pipeline?.name}?</DialogTitle>
        <DialogDescription>This can't be undone.</DialogDescription>
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={onClose} disabled={remove.isPending}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={remove.isPending}
            onClick={() => pipeline && remove.mutate(pipeline)}
          >
            {remove.isPending ? "Deleting…" : "Delete"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
