// Mirrors the backend response shapes in workflow-backend/app/api/models.py
// and the definition contract in PROMPT.md A2. Keep these in sync by hand;
// there is no shared schema between the two projects.

// ---------------------------------------------------------------------------
// Workflow definition contract (A2)
// ---------------------------------------------------------------------------

export interface BlockPosition {
  x: number;
  y: number;
}

export interface BlockDefinition {
  type: string;
  config: Record<string, unknown>;
  depends_on: string[];
  /** A list for every block type except switch, where it's keyed by output name. */
  next: string[] | Record<string, string[]>;
  position: BlockPosition;
  notes: string;
}

export interface WorkflowDefinition {
  blocks: Record<string, BlockDefinition>;
}

// ---------------------------------------------------------------------------
// Block schemas (A7 / B7)
// ---------------------------------------------------------------------------

export type FieldType =
  | "string"
  | "number"
  | "boolean"
  | "options"
  | "json"
  | "key_value_list"
  | "field_definitions"
  | "switch_rules";

export interface FieldOption {
  label: string;
  value: string;
}

export type ShowWhenValue = string | number | boolean | (string | number | boolean)[];

export interface FieldSchema {
  name: string;
  label: string;
  type: FieldType;
  required?: boolean;
  default?: unknown;
  options?: FieldOption[];
  placeholder?: string;
  description?: string;
  sensitive?: boolean;
  show_when?: Record<string, ShowWhenValue>;
}

export interface BlockTypeSchema {
  name: string;
  category: string;
  description?: string;
  fields: FieldSchema[];
}

export interface BlockSchemaResponse {
  type: string;
  schema: BlockTypeSchema;
}

// ---------------------------------------------------------------------------
// Pipelines (A9)
// ---------------------------------------------------------------------------

export type RunStatus = "pending" | "running" | "succeeded" | "failed" | "waiting";
export type BlockExecutionStatus =
  | "pending"
  | "ready"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped"
  | "waiting";

export interface PipelineListItem {
  id: string;
  name: string;
  is_active: boolean;
  is_template: boolean;
  block_count: number;
  last_run_status: RunStatus | null;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PipelineResponse {
  id: string;
  name: string;
  definition: WorkflowDefinition;
  is_active: boolean;
  is_template: boolean;
  created_at: string;
  updated_at: string;
}

export interface BlockError {
  message: string;
  type: string;
  attempts: number;
  retryable: boolean;
}

export interface RunErrorSummary extends BlockError {
  block_id: string;
}

export interface LatestBlockOutput {
  status: BlockExecutionStatus;
  output: Record<string, unknown> | null;
  error: BlockError | null;
  run_id: string;
  finished_at: string | null;
}

export type LatestOutputs = Record<string, LatestBlockOutput>;

export interface InvalidWorkflowError {
  detail: "Invalid workflow";
  problems: string[];
}

// ---------------------------------------------------------------------------
// Runs (A9)
// ---------------------------------------------------------------------------

export interface RunListItem {
  id: string;
  pipeline_id: string;
  pipeline_name: string;
  status: RunStatus;
  input_data: Record<string, unknown> | null;
  error_summary: RunErrorSummary | null;
  total_blocks: number;
  blocks_ran: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface RunListResponse {
  items: RunListItem[];
  total: number;
}

export interface RunResponse {
  id: string;
  pipeline_id: string;
  status: RunStatus;
  run_type: "production" | "test";
  total_blocks: number;
  blocks_remaining: number;
  error_summary: RunErrorSummary | null;
  input_data: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunDetailResponse extends RunResponse {
  pipeline_snapshot: WorkflowDefinition;
  pipeline_name: string;
  pipeline_updated_at: string;
}

export interface BlockExecutionResponse {
  block_id: string;
  block_type: string;
  status: BlockExecutionStatus;
  retry_count: number;
  resolved_config: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: BlockError | null;
  started_at: string | null;
  finished_at: string | null;
}

// ---------------------------------------------------------------------------
// WebSocket events (A5)
// ---------------------------------------------------------------------------

export interface BlockStatusEvent {
  type: "block_status";
  run_id: string;
  block_id: string;
  status: BlockExecutionStatus;
  retry_count: number;
  error: BlockError | null;
}

export interface RunStatusEvent {
  type: "run_status";
  run_id: string;
  pipeline_id: string;
  status: RunStatus;
  error_summary: RunErrorSummary | null;
}

export type RunEvent = BlockStatusEvent | RunStatusEvent;
