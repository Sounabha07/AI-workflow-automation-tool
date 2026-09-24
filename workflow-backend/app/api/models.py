from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class CreatePipelineRequest(BaseModel):
    name: str
    definition: dict


class UpdatePipelineRequest(BaseModel):
    name: str | None = None
    definition: dict | None = None


class PipelineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    definition: dict
    is_template: bool
    created_at: datetime
    updated_at: datetime


class PipelineListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    is_template: bool
    created_at: datetime
    updated_at: datetime


class TriggerRunRequest(BaseModel):
    pipeline_id: UUID
    input_data: dict = {}


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
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


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


class TestStepRequest(BaseModel):
    pipeline_id: UUID
    block_id: str
    input_data: dict = {}


class TestStepResponse(BaseModel):
    run_id: UUID


class ResumeRequest(BaseModel):
    result_data: dict


class ResumeResponse(BaseModel):
    block_id: str
    run_id: UUID
    status: str


class BlockSchemaResponse(BaseModel):
    type: str
    schema_: dict = Field(alias="schema")
    model_config = ConfigDict(populate_by_name=True)
