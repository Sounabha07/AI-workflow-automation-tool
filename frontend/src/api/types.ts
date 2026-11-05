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
  /** Multi-line string; {{ }} expressions can sit anywhere in it. */
  | "text"
  | "number"
  | "boolean"
  | "options"
  | "json"
  | "key_value_list"
  | "field_definitions"
  | "switch_rules"
  /** Picks a saved credential by id (see /credentials). */
  | "credential"
  /** An agent's connected tool block ids; set by wiring, shown read-only. */
  | "tool_list";

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
  /** For "credential" fields: which credential types can be picked. */
  credential_types?: string[];
  /** "tool": rendered by the tool definition panel, only when the block is an agent's tool. */
  section?: "tool";
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
  /** Whether an agent can call this block type as a tool. */
  usable_as_tool?: boolean;
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
  | "waiting"
  | "cancelled";

/** Which kind of trigger started a run (or starts a workflow). */
export type TriggerType = "manual" | "schedule" | "webhook";

/** A schedule or webhook trigger block, from the backend's trigger index. */
export interface PipelineTrigger {
  block_id: string;
  type: "schedule" | "webhook";
  webhook_url: string | null;
  cron: string | null;
  timezone: string | null;
  next_run_at: string | null;
  last_fired_at: string | null;
}

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
  trigger_type: TriggerType;
  /** Soonest scheduled run; null unless the workflow is active and scheduled. */
  next_run_at: string | null;
}

export interface PipelineResponse {
  id: string;
  name: string;
  definition: WorkflowDefinition;
  is_active: boolean;
  is_template: boolean;
  created_at: string;
  updated_at: string;
  triggers: PipelineTrigger[];
  /** Each Wait for Input block's fixed resume link (resumes its longest-waiting run). */
  resume_links: { block_id: string; url: string }[];
  /** Valid, but worth a look (e.g. schema keywords Gemini ignores). */
  warnings?: string[];
}

export interface BlockError {
  message: string;
  type: string;
  attempts: number;
  retryable: boolean;
  /** Structured context, e.g. an agent's {stop_reason, trace, usage}. */
  detail?: Record<string, unknown>;
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
  trigger_type: TriggerType;
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
  trigger_type: TriggerType;
  trigger_payload: Record<string, unknown> | null;
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
  /** Wait for Input blocks only. */
  resume_url: string | null;
  wait_deadline: string | null;
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
  /** Sent with a wait block's "waiting" event. */
  resume_url?: string;
  wait_deadline?: string;
}

export interface RunStatusEvent {
  type: "run_status";
  run_id: string;
  pipeline_id: string;
  status: RunStatus;
  error_summary: RunErrorSummary | null;
}

/** One agent step was checkpointed (a model turn or a tool call). */
export interface AgentStepEvent {
  type: "agent.step";
  run_id: string;
  block_id: string;
  step_index: number;
  kind: "model" | "tool";
  tool_name: string | null;
  status: "started" | "completed" | "failed";
}

export type RunEvent = BlockStatusEvent | RunStatusEvent | AgentStepEvent;

// ---------------------------------------------------------------------------
// Agents
// ---------------------------------------------------------------------------

export interface AgentTraceStep {
  step_index: number;
  kind: "model" | "tool";
  status: "started" | "completed" | "failed";
  duration_ms: number | null;
  replayed: boolean;
  // model turns
  text?: string;
  tool_calls?: { id: string; name: string; args: unknown }[];
  usage?: Record<string, number | null> | null;
  nudge?: string;
  // tool calls
  tool_name?: string;
  tool_call_id?: string;
  side_effects?: boolean | null;
  args?: unknown;
  request?: Record<string, unknown> | null;
  response?: Record<string, unknown> | null;
  result?: unknown;
  attempts?: number | null;
  outcome_unknown?: boolean;
  error?: string | null;
}

export interface TestToolResponse {
  ok: boolean;
  request: Record<string, unknown> | null;
  response: Record<string, unknown>;
  result: unknown;
  error: string | null;
  status: number | null;
  side_effects: boolean;
  attempts: number;
  duration_ms: number;
}

// ---------------------------------------------------------------------------
// Saved credentials. Secrets are write-only: responses carry only a hint.
// ---------------------------------------------------------------------------

export interface Credential {
  id: string;
  name: string;
  type: string;
  type_label: string;
  hint: string;
  created_at: string;
  updated_at: string;
}

export interface CredentialType {
  type: string;
  label: string;
  fields: { name: string; label: string }[];
}
