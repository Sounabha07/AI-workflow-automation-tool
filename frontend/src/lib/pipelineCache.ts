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
