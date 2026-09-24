import type { QueryClient } from "@tanstack/react-query";
import type { PipelineListItem, PipelineResponse } from "@/api/types";

/** Writes a pipeline's is_active into the cached list and detail queries, so
 * the UI reflects it immediately (e.g. from POST /runs' pipeline_is_active). */
export function applyPipelineActive(queryClient: QueryClient, pipelineId: string, isActive: boolean) {
  queryClient.setQueryData<PipelineListItem[]>(["pipelines"], (old) =>
    old?.map((p) => (p.id === pipelineId ? { ...p, is_active: isActive } : p))
  );
  queryClient.setQueryData<PipelineResponse>(["pipeline", pipelineId], (old) =>
    old ? { ...old, is_active: isActive } : old
  );
}

/** After a successful rename (PUT), update the detail and list entries. */
export function applyPipelineUpdate(queryClient: QueryClient, pipeline: PipelineResponse) {
  queryClient.setQueryData<PipelineResponse>(["pipeline", pipeline.id], pipeline);
  queryClient.setQueryData<PipelineListItem[]>(["pipelines"], (old) =>
    old?.map((p) => (p.id === pipeline.id ? { ...p, name: pipeline.name, updated_at: pipeline.updated_at } : p))
  );
}

/** After a successful DELETE, drop the pipeline from every cache entry. */
export function removePipelineFromCache(queryClient: QueryClient, pipelineId: string) {
  queryClient.setQueryData<PipelineListItem[]>(["pipelines"], (old) => old?.filter((p) => p.id !== pipelineId));
  queryClient.removeQueries({ queryKey: ["pipeline", pipelineId] });
}
