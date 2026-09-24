import json
from uuid import UUID

from fastapi import APIRouter

import engine
from db import get_connection
from app.api.models import (
    TriggerRunRequest,
    RunResponse,
    BlockExecutionResponse,
    TestStepRequest,
    TestStepResponse,
)

router = APIRouter()


def _parse_jsonb(v) -> dict:
    return json.loads(v) if isinstance(v, str) else (v or {})


def _row_to_run_response(row: dict) -> RunResponse:
    error_summary = row.get("error_summary")
    if isinstance(error_summary, str):
        error_summary = json.loads(error_summary)

    input_data = row.get("input_data")
    if isinstance(input_data, str):
        input_data = json.loads(input_data)

    return RunResponse(
        id=row["id"],
        pipeline_id=row["pipeline_id"],
        status=row["status"],
        run_type=row["run_type"],
        total_blocks=row["total_blocks"],
        blocks_remaining=row["blocks_remaining"],
        error_summary=error_summary,
        input_data=input_data,
        created_at=row["created_at"],
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
    )


def _row_to_block_execution_response(row: dict) -> BlockExecutionResponse:
    return BlockExecutionResponse(
        block_id=row["block_id"],
        block_type=row["block_type"],
        status=row["status"],
        retry_count=row["retry_count"],
        resolved_config=_parse_jsonb(row.get("resolved_config")) if row.get("resolved_config") else None,
        output=_parse_jsonb(row.get("output")) if row.get("output") else None,
        error=_parse_jsonb(row.get("error")) if row.get("error") else None,
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
    )


# Route registration order matters — FastAPI matches top to bottom.
# POST /runs/test must be before GET /runs/{run_id}.

@router.post("/test", status_code=202, response_model=TestStepResponse)
async def test_step(body: TestStepRequest) -> TestStepResponse:
    conn = await get_connection()
    try:
        # 1. Fetch pipeline from DB
        pipeline_row = await conn.fetchrow(
            "SELECT * FROM pipelines WHERE id = $1", body.pipeline_id
        )
        if pipeline_row is None:
            raise ValueError(f"Pipeline {body.pipeline_id} not found")

        # 2. Parse definition JSONB
        definition = _parse_jsonb(pipeline_row["definition"])

        # 3. Confirm block_id exists
        if body.block_id not in definition.get("blocks", {}):
            raise ValueError(
                f"Block '{body.block_id}' not found in pipeline definition"
            )

        # 4. Get block_def
        block_def = definition["blocks"][body.block_id]

        # 5. If input_block, inject values
        if block_def.get("type") == "input_block":
            block_def = dict(block_def)
            block_def["config"] = {
                **block_def.get("config", {}),
                "values": body.input_data
            }

        # 6. Build minimal snapshot
        minimal_snapshot = {
            "blocks": {
                body.block_id: {
                    **block_def,
                    "depends_on": [],
                    "next": []
                }
            }
        }

        # 7. Inside a transaction: insert run + block_execution
        async with conn.transaction():
            run_id = await conn.fetchval(
                """
                INSERT INTO runs (
                    pipeline_id, run_type, pipeline_snapshot,
                    input_data, total_blocks, blocks_remaining,
                    status, started_at
                )
                VALUES ($1, 'test', $2, $3, 1, 1, 'running', NOW())
                RETURNING id
                """,
                body.pipeline_id,
                json.dumps(minimal_snapshot),
                json.dumps(body.input_data),
            )

            await conn.execute(
                """
                INSERT INTO block_executions (
                    run_id, block_id, block_type, status, remaining_deps
                )
                VALUES ($1, $2, $3, 'ready', 0)
                """,
                run_id,
                body.block_id,
                block_def["type"],
            )
    finally:
        await conn.close()

    # 8. After commit, dispatch task
    from tasks import execute_block_task
    execute_block_task.delay(str(run_id), body.block_id)

    # 9. Return 202
    return TestStepResponse(run_id=run_id)


@router.post("", status_code=202)
async def trigger_run(body: TriggerRunRequest) -> dict:
    conn = await get_connection()
    try:
        pipeline = await conn.fetchrow(
            "SELECT id FROM pipelines WHERE id = $1", body.pipeline_id
        )
        if pipeline is None:
            raise ValueError(f"Pipeline {body.pipeline_id} not found")
    finally:
        await conn.close()

    run_id = await engine.start_run(
        str(body.pipeline_id),
        input_data=body.input_data,
    )
    return {"run_id": run_id, "status": "running"}


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: UUID) -> RunResponse:
    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT * FROM runs WHERE id = $1", run_id)
        if row is None:
            raise ValueError(f"Run {run_id} not found")
        return _row_to_run_response(dict(row))
    finally:
        await conn.close()


@router.get("/{run_id}/blocks", response_model=list[BlockExecutionResponse])
async def get_run_blocks(run_id: UUID) -> list[BlockExecutionResponse]:
    conn = await get_connection()
    try:
        rows = await conn.fetch(
            """
            SELECT * FROM block_executions
            WHERE run_id = $1
            ORDER BY created_at
            """,
            run_id,
        )
        return [_row_to_block_execution_response(dict(row)) for row in rows]
    finally:
        await conn.close()


@router.get("/{run_id}/blocks/{block_id}", response_model=BlockExecutionResponse)
async def get_run_block(run_id: UUID, block_id: str) -> BlockExecutionResponse:
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT * FROM block_executions
            WHERE run_id = $1 AND block_id = $2
            """,
            run_id,
            block_id,
        )
        if row is None:
            raise ValueError(
                f"Block execution for run={run_id}, block={block_id} not found"
            )
        return _row_to_block_execution_response(dict(row))
    finally:
        await conn.close()
