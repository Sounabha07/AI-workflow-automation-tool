import { apiFetch } from "./client";
import type { TestToolResponse, WorkflowDefinition } from "./types";

/** POST /tools/test: one call to a tool block, no agent or model involved. */
export function testTool(body: {
  definition: WorkflowDefinition;
  block_id: string;
  args: Record<string, unknown>;
  pipeline_id?: string | null;
}): Promise<TestToolResponse> {
  return apiFetch("/tools/test", { method: "POST", body });
}
