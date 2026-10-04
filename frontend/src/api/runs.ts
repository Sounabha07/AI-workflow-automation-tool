import { ApiError, apiFetch } from "./client";
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
): Promise<{ run_id: string; status: string; pipeline_is_active: boolean }> {
  return apiFetch("/runs", { method: "POST", body: { pipeline_id, input_data } });
}

export interface TestStepBody {
  pipeline_id: string;
  block_id: string;
  input_data?: Record<string, unknown>;
  definition?: WorkflowDefinition;
}

/** POSTs a JSON object to a waiting block's resume URL. It's the full URL
 * the backend hands out, so this works whatever PUBLIC_BASE_URL is. */
export async function resumeBlock(resumeUrl: string, data: Record<string, unknown>): Promise<void> {
  const res = await fetch(resumeUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    let detail = `Resume failed with status ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body; keep the status message.
    }
    throw new ApiError(res.status, detail);
  }
}

export function testStep(body: TestStepBody): Promise<{ run_id: string }> {
  return apiFetch("/runs/test", { method: "POST", body });
}
