import json
from uuid import UUID

from fastapi import APIRouter, Query

import engine
from db import get_connection
from app.errors import NotFoundError
from app.validation import ancestors, ensure_valid
from app.api.routes_pipelines import fetch_latest_outputs
from app.api.models import (
    TriggerRunRequest,
    RunResponse,
    RunDetailResponse,
    RunListItem,
    RunListResponse,
    BlockExecutionResponse,
    TestStepRequest,
    TestStepResponse,
)

router = APIRouter()


def _parse_jsonb(v) -> dict:
    return json.loads(v) if isinstance(v, str) else (v or {})


def _parse_optional_jsonb(v):
    return json.loads(v) if isinstance(v, str) else v


def _run_fields(row: dict) -> dict:
    return dict(
        id=row["id"],
        pipeline_id=row["pipeline_id"],
        status=row["status"],
        run_type=row["run_type"],
        total_blocks=row["total_blocks"],
        blocks_remaining=row["blocks_remaining"],
        error_summary=_parse_optional_jsonb(row.get("error_summary")),
        input_data=_parse_optional_jsonb(row.get("input_data")),
        created_at=row["created_at"],
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
    )


def _row_to_run_response(row: dict) -> RunResponse:
    return RunResponse(**_run_fields(row))


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
    # Test steps are manual, so they run regardless of pipelines.is_active.
    conn = await get_connection()
    try:
        # 1. Fetch pipeline from DB
        pipeline_row = await conn.fetchrow(
            "SELECT * FROM pipelines WHERE id = $1", body.pipeline_id
        )
        if pipeline_row is None:
            raise NotFoundError(f"Pipeline {body.pipeline_id} not found")

        # 2. Use the supplied (unsaved) definition if given, else the saved one
        if body.definition is not None:
            ensure_valid(body.definition)
            definition = body.definition
        else:
            definition = _parse_jsonb(pipeline_row["definition"])

        # 3. Confirm block_id exists
        if body.block_id not in definition.get("blocks", {}):
            raise ValueError(
                f"Block '{body.block_id}' not found in pipeline definition"
            )

        # 4. Get block_def
        block_def = definition["blocks"][body.block_id]

        # 5. Seed upstream outputs: each ancestor's latest succeeded output
        upstream = ancestors(definition, body.block_id)
        latest = await fetch_latest_outputs(conn, body.pipeline_id, ("succeeded",))
        seed_outputs = {
            bid: v["output"] for bid, v in latest.items()
            if bid in upstream and v["output"] is not None
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
                    input_data, seed_outputs, total_blocks, blocks_remaining,
                    status, started_at
                )
                VALUES ($1, 'test', $2, $3, $4, 1, 1, 'running', NOW())
                RETURNING id
                """,
                body.pipeline_id,
                json.dumps(minimal_snapshot),
                json.dumps(body.input_data),
                json.dumps(seed_outputs, default=str),
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

    # 8. After commit, publish and dispatch task
    engine.publish_run_started(str(run_id), body.pipeline_id)
    from tasks import execute_block_task
    execute_block_task.delay(str(run_id), body.block_id)

    # 9. Return 202
    return TestStepResponse(run_id=run_id)


@router.get("", response_model=RunListResponse)
async def list_runs(
    pipeline_name: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> RunListResponse:
    where = ["r.run_type != 'test'"]
    params: list = []
    if pipeline_name:
        params.append(f"%{pipeline_name}%")
        where.append(f"p.name ILIKE ${len(params)}")
    if status:
        params.append(status)
        where.append(f"r.status::text = ${len(params)}")
    where_sql = " AND ".join(where)

    conn = await get_connection()
    try:
        total = await conn.fetchval(
            f"SELECT count(*) FROM runs r JOIN pipelines p ON p.id = r.pipeline_id WHERE {where_sql}",
            *params,
        )
        rows = await conn.fetch(
            f"""
            SELECT r.id, r.pipeline_id, p.name AS pipeline_name, r.status,
                   r.input_data, r.error_summary, r.total_blocks,
                   (SELECT count(*) FROM block_executions be
                    WHERE be.run_id = r.id
                      AND be.status IN ('succeeded', 'failed'))::int AS blocks_ran,
                   r.created_at, r.started_at, r.finished_at,
                   (EXTRACT(EPOCH FROM (r.finished_at - r.started_at)) * 1000)::bigint
                       AS duration_ms
            FROM runs r
            JOIN pipelines p ON p.id = r.pipeline_id
            WHERE {where_sql}
            ORDER BY r.created_at DESC
            LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
            """,
            *params,
            limit,
            offset,
        )
    finally:
        await conn.close()

    items = [
        RunListItem(
            **{
                **dict(row),
                "input_data": _parse_optional_jsonb(row["input_data"]),
                "error_summary": _parse_optional_jsonb(row["error_summary"]),
            }
        )
        for row in rows
    ]
    return RunListResponse(items=items, total=total)


@router.post("", status_code=202)
async def trigger_run(body: TriggerRunRequest) -> dict:
    # Manual runs are always allowed, regardless of pipelines.is_active.
    # is_active only gates automatic triggers (webhook, schedule).
    conn = await get_connection()
    try:
        pipeline = await conn.fetchrow(
            "SELECT id FROM pipelines WHERE id = $1", body.pipeline_id
        )
        if pipeline is None:
            raise NotFoundError(f"Pipeline {body.pipeline_id} not found")
    finally:
        await conn.close()

    run_id = await engine.start_run(
        str(body.pipeline_id),
        input_data=body.input_data,
    )
    return {"run_id": run_id, "status": "running"}


@router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run(run_id: UUID) -> RunDetailResponse:
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT r.*, p.name AS pipeline_name, p.updated_at AS pipeline_updated_at
            FROM runs r
            JOIN pipelines p ON p.id = r.pipeline_id
            WHERE r.id = $1
            """,
            run_id,
        )
        if row is None:
            raise NotFoundError(f"Run {run_id} not found")
        d = dict(row)
        return RunDetailResponse(
            **_run_fields(d),
            pipeline_snapshot=_parse_jsonb(d["pipeline_snapshot"]),
            pipeline_name=d["pipeline_name"],
            pipeline_updated_at=d["pipeline_updated_at"],
        )
    finally:
        await conn.close()


@router.get("/{run_id}/blocks", response_model=list[BlockExecutionResponse])
async def get_run_blocks(run_id: UUID) -> list[BlockExecutionResponse]:
    conn = await get_connection()
    try:
        if await conn.fetchval("SELECT 1 FROM runs WHERE id = $1", run_id) is None:
            raise NotFoundError(f"Run {run_id} not found")
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
            raise NotFoundError(
                f"Block execution for run={run_id}, block={block_id} not found"
            )
        return _row_to_block_execution_response(dict(row))
    finally:
        await conn.close()
