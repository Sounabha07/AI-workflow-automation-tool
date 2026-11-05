from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class CreatePipelineRequest(BaseModel):
    name: str
    definition: dict


class UpdatePipelineRequest(BaseModel):
    name: str | None = None
    definition: dict | None = None


class PatchPipelineRequest(BaseModel):
    is_active: bool


class PipelineTrigger(BaseModel):
    """One schedule or webhook trigger block, from the pipeline_triggers index."""
    block_id: str
    type: str  # "schedule" | "webhook"
    webhook_url: str | None = None
    cron: str | None = None
    timezone: str | None = None
    next_run_at: datetime | None = None
    last_fired_at: datetime | None = None


class PipelineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    definition: dict
    is_active: bool
    is_template: bool
    created_at: datetime
    updated_at: datetime
    triggers: list[PipelineTrigger] = []
    # Each Wait for Input block's fixed resume link: [{block_id, url}].
    resume_links: list[dict] = []
    # Valid, but worth a look (e.g. schema keywords Gemini ignores).
    warnings: list[str] = []


class PipelineListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    is_active: bool
    is_template: bool
    block_count: int
    last_run_status: str | None = None
    last_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # "manual" | "schedule" | "webhook", from the definition's trigger block.
    trigger_type: str = "manual"
    # Soonest scheduled run; only set while the workflow is active.
    next_run_at: datetime | None = None


class LatestBlockOutput(BaseModel):
    status: str
    output: dict | None = None
    error: dict | None = None
    run_id: UUID
    finished_at: datetime | None = None


class TriggerRunRequest(BaseModel):
    pipeline_id: UUID
    input_data: dict = {}
    # Sample output for the trigger block, e.g. a webhook body to test with.
    trigger_payload: dict | None = None


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    pipeline_id: UUID
    status: str
    run_type: str
    total_blocks: int
    blocks_remaining: int
    error_summary: dict | None = None
    input_data: dict | None = None
    trigger_type: str = "manual"
    trigger_payload: dict | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunDetailResponse(RunResponse):
    pipeline_snapshot: dict
    pipeline_name: str
    pipeline_updated_at: datetime


class RunListItem(BaseModel):
    id: UUID
    pipeline_id: UUID
    pipeline_name: str
    status: str
    trigger_type: str = "manual"
    input_data: dict | None = None
    error_summary: dict | None = None
    total_blocks: int
    blocks_ran: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None


class RunListResponse(BaseModel):
    items: list[RunListItem]
    total: int


class BlockExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    block_id: str
    block_type: str
    status: str
    retry_count: int
    resolved_config: dict | None = None
    output: dict | None = None
    error: dict | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Wait for Input blocks only.
    resume_url: str | None = None
    wait_deadline: datetime | None = None


class TestStepRequest(BaseModel):
    pipeline_id: UUID
    block_id: str
    input_data: dict = {}
    definition: dict | None = None
    # Output for the trigger block when it is the one tested, or seeded as
    # its output when testing a block downstream of it.
    trigger_payload: dict | None = None


class TestStepResponse(BaseModel):
    run_id: UUID


class ResumeResponse(BaseModel):
    run_id: UUID
    block_id: str
    status: str


class WebhookAcceptedResponse(BaseModel):
    run_id: UUID


class SchedulePreviewRequest(BaseModel):
    cron: str
    timezone: str = "UTC"


class SchedulePreviewResponse(BaseModel):
    times: list[datetime]


class BlockSchemaResponse(BaseModel):
    type: str
    schema_: dict = Field(alias="schema")
    # Whether an agent can call this block type as a tool.
    usable_as_tool: bool = False
    model_config = ConfigDict(populate_by_name=True)


class CreateCredentialRequest(BaseModel):
    name: str
    type: str
    # Secret fields for the type, e.g. {"api_key": "..."}. Never returned.
    data: dict


class UpdateCredentialRequest(BaseModel):
    name: str | None = None
    data: dict | None = None


class CredentialResponse(BaseModel):
    id: UUID
    name: str
    type: str
    type_label: str
    hint: str
    created_at: datetime
    updated_at: datetime


class CredentialTypeField(BaseModel):
    name: str
    label: str


class CredentialTypeResponse(BaseModel):
    type: str
    label: str
    fields: list[CredentialTypeField]
