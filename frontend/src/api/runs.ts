import { apiFetch } from "./client";
import type {
  BlockExecutionResponse,
  RunDetailResponse,
  RunListResponse,
  WorkflowDefinition,
} from "./types";

export interface ListRunsParams {
  pipeline_name?: string;
  status?: string;
  limit?: number;
  offset?: number;
  [key: string]: string | number | boolean | undefined;
}

export function listRuns(params: ListRunsParams = {}): Promise<RunListResponse> {
  return apiFetch("/runs", { params });
}

export function getRun(id: string): Promise<RunDetailResponse> {
  return apiFetch(`/runs/${id}`);
}

export function getRunBlocks(id: string): Promise<BlockExecutionResponse[]> {
  return apiFetch(`/runs/${id}/blocks`);
}

export function getRunBlock(runId: string, blockId: string): Promise<BlockExecutionResponse> {
  return apiFetch(`/runs/${runId}/blocks/${blockId}`);
}

export function triggerRun(
  pipeline_id: string,
  input_data: Record<string, unknown> = {}
): Promise<{ run_id: string; status: string }> {
  return apiFetch("/runs", { method: "POST", body: { pipeline_id, input_data } });
}

export interface TestStepBody {
  pipeline_id: string;
  block_id: string;
  input_data?: Record<string, unknown>;
  definition?: WorkflowDefinition;
}

export function testStep(body: TestStepBody): Promise<{ run_id: string }> {
  return apiFetch("/runs/test", { method: "POST", body });
}
