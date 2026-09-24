import type { QueryClient } from "@tanstack/react-query";
import type { PipelineListItem, PipelineResponse, RunDetailResponse, RunListResponse } from "@/api/types";

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

/** After a successful DELETE, drop the pipeline and its run history (which
 * the backend cascade-deleted) from every cache entry, so History never shows
 * rows for runs that no longer exist. */
export function removePipelineFromCache(queryClient: QueryClient, pipelineId: string) {
  queryClient.setQueryData<PipelineListItem[]>(["pipelines"], (old) => old?.filter((p) => p.id !== pipelineId));
  queryClient.removeQueries({ queryKey: ["pipeline", pipelineId] });
  queryClient.removeQueries({ queryKey: ["latestOutputs", pipelineId] });

  // Run ids of this pipeline that any cached list or detail knows about.
  const runIds = new Set<string>();
  for (const [, data] of queryClient.getQueriesData<RunListResponse>({ queryKey: ["runs"] })) {
    data?.items.forEach((r) => r.pipeline_id === pipelineId && runIds.add(r.id));
  }
  for (const [key, data] of queryClient.getQueriesData<RunDetailResponse>({ queryKey: ["run"] })) {
    if (data?.pipeline_id === pipelineId) runIds.add(String(key[1]));
  }
  for (const id of runIds) {
    queryClient.removeQueries({ queryKey: ["run", id] });
    queryClient.removeQueries({ queryKey: ["runBlocks", id] });
  }
  // History lists are keyed by filter/page; drop them all and let them refetch.
  queryClient.removeQueries({ queryKey: ["runs"] });
}
