import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { patchPipelineActive } from "@/api/pipelines";
import { ApiError } from "@/api/client";
import type { PipelineListItem, PipelineResponse } from "@/api/types";
import { applyPipelineActive } from "@/lib/pipelineCache";

/** PATCH a pipeline's is_active. Used by every Active switch, so they all
 * update the same cache entries (the pipelines list and the pipeline
 * detail) that POST /runs also writes via applyPipelineActive. */
export function useSetPipelineActive() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) => patchPipelineActive(id, is_active),
    onMutate: async ({ id, is_active }) => {
      await queryClient.cancelQueries({ queryKey: ["pipelines"] });
      await queryClient.cancelQueries({ queryKey: ["pipeline", id] });
      const previousList = queryClient.getQueryData<PipelineListItem[]>(["pipelines"]);
      const previousDetail = queryClient.getQueryData<PipelineResponse>(["pipeline", id]);
      applyPipelineActive(queryClient, id, is_active);
      return { previousList, previousDetail };
    },
    onError: (err, { id }, context) => {
      queryClient.setQueryData(["pipelines"], context?.previousList);
      queryClient.setQueryData(["pipeline", id], context?.previousDetail);
      toast.error(err instanceof ApiError ? err.message : "Couldn't update this workflow");
    },
    onSuccess: (item, { id }) => {
      applyPipelineActive(queryClient, id, item.is_active);
      toast.success(`${item.name} is now ${item.is_active ? "active" : "inactive"}`);
    },
    onSettled: (_data, _err, { id }) => {
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
      queryClient.invalidateQueries({ queryKey: ["pipeline", id] });
    },
  });
}
