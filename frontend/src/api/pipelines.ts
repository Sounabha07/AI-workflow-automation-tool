import { apiFetch } from "./client";
import type {
  LatestOutputs,
  PipelineListItem,
  PipelineResponse,
  RunResponse,
  WorkflowDefinition,
} from "./types";

export function listPipelines(): Promise<PipelineListItem[]> {
  return apiFetch("/pipelines");
}

export function getPipeline(id: string): Promise<PipelineResponse> {
  return apiFetch(`/pipelines/${id}`);
}

export function createPipeline(
  name: string,
  definition: WorkflowDefinition
): Promise<PipelineResponse> {
  return apiFetch("/pipelines", { method: "POST", body: { name, definition } });
}

export function updatePipeline(
  id: string,
  body: { name?: string; definition?: WorkflowDefinition }
): Promise<PipelineResponse> {
  return apiFetch(`/pipelines/${id}`, { method: "PUT", body });
}

export function patchPipelineActive(id: string, is_active: boolean): Promise<PipelineListItem> {
  return apiFetch(`/pipelines/${id}`, { method: "PATCH", body: { is_active } });
}

export function getLatestOutputs(id: string): Promise<LatestOutputs> {
  return apiFetch(`/pipelines/${id}/latest-outputs`);
}

export function getPipelineRuns(id: string): Promise<RunResponse[]> {
  return apiFetch(`/pipelines/${id}/runs`);
}
