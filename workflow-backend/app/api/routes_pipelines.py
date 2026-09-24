import json
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import Response

from db import get_connection
from app.errors import NotFoundError
from app.validation import ensure_valid
from app.api.models import (
    CreatePipelineRequest,
    UpdatePipelineRequest,
    PatchPipelineRequest,
    PipelineResponse,
    PipelineListItem,
    LatestBlockOutput,
    RunResponse,
)

router = APIRouter()

# One row per pipeline, with the newest non-test run joined in.
_LIST_SQL = """
    SELECT p.id, p.name, p.is_active, p.is_template, p.created_at, p.updated_at,
           CASE WHEN jsonb_typeof(p.definition->'blocks') = 'object'
                THEN (SELECT count(*) FROM jsonb_object_keys(p.definition->'blocks'))
                ELSE 0 END::int AS block_count,
           lr.status AS last_run_status,
           lr.created_at AS last_run_at
    FROM pipelines p
    LEFT JOIN LATERAL (
        SELECT r.status, r.created_at
        FROM runs r
        WHERE r.pipeline_id = p.id AND r.run_type != 'test'
        ORDER BY r.created_at DESC
        LIMIT 1
    ) lr ON TRUE
"""


def _parse_jsonb(v) -> dict:
    return json.loads(v) if isinstance(v, str) else (v or {})


def _row_to_pipeline_response(row: dict) -> PipelineResponse:
    return PipelineResponse(
        id=row["id"],
        name=row["name"],
        definition=_parse_jsonb(row["definition"]),
        is_active=row["is_active"],
        is_template=row["is_template"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_list_item(row) -> PipelineListItem:
    return PipelineListItem(**dict(row))


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


async def fetch_latest_outputs(
    conn, pipeline_id, statuses: tuple[str, ...] = ("succeeded", "failed")
) -> dict[str, dict]:
    """For each block_id, its newest execution in any run of this pipeline
    (test runs included) whose status is one of `statuses`."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (be.block_id)
               be.block_id, be.status, be.output, be.error, be.run_id, be.finished_at
        FROM block_executions be
        JOIN runs r ON r.id = be.run_id
        WHERE r.pipeline_id = $1
          AND be.status::text = ANY($2::text[])
        ORDER BY be.block_id, be.finished_at DESC NULLS LAST
        """,
        pipeline_id,
        list(statuses),
    )
    return {
        r["block_id"]: {
            "status": r["status"],
            "output": _parse_jsonb(r["output"]) if r["output"] is not None else None,
            "error": _parse_jsonb(r["error"]) if r["error"] is not None else None,
            "run_id": r["run_id"],
            "finished_at": r["finished_at"],
        }
        for r in rows
    }


@router.post("", status_code=201, response_model=PipelineResponse)
async def create_pipeline(body: CreatePipelineRequest) -> PipelineResponse:
    ensure_valid(body.definition)
    conn = await get_connection()
    try:
        async with conn.transaction():
            # is_active defaults to FALSE: new workflows never auto-trigger.
            row = await conn.fetchrow(
                """
                INSERT INTO pipelines (name, definition)
                VALUES ($1, $2)
                RETURNING *
                """,
                body.name,
                json.dumps(body.definition),
            )
        d = dict(row)
        return _row_to_pipeline_response(d)
    finally:
        await conn.close()


@router.get("", response_model=list[PipelineListItem])
async def list_pipelines() -> list[PipelineListItem]:
    conn = await get_connection()
    try:
        rows = await conn.fetch(_LIST_SQL + " ORDER BY p.created_at DESC")
        return [_row_to_list_item(row) for row in rows]
    finally:
        await conn.close()


@router.get("/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(pipeline_id: UUID) -> PipelineResponse:
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM pipelines WHERE id = $1", pipeline_id
        )
        if row is None:
            raise NotFoundError(f"Pipeline {pipeline_id} not found")
        return _row_to_pipeline_response(dict(row))
    finally:
        await conn.close()


@router.put("/{pipeline_id}", response_model=PipelineResponse)
async def update_pipeline(
    pipeline_id: UUID, body: UpdatePipelineRequest
) -> PipelineResponse:
    if body.name is None and body.definition is None:
        raise ValueError("At least one of 'name' or 'definition' must be provided")
    if body.name is not None and not body.name.strip():
        raise ValueError("Workflow name can't be empty")
    if body.definition is not None:
        ensure_valid(body.definition)

    conn = await get_connection()
    try:
        set_clauses = ["updated_at = NOW()"]
        params: list = []
        idx = 1

        if body.name is not None:
            set_clauses.append(f"name = ${idx}")
            params.append(body.name)
            idx += 1

        if body.definition is not None:
            set_clauses.append(f"definition = ${idx}")
            params.append(json.dumps(body.definition))
            idx += 1

        params.append(pipeline_id)
        sql = f"UPDATE pipelines SET {', '.join(set_clauses)} WHERE id = ${idx} RETURNING *"

        async with conn.transaction():
            row = await conn.fetchrow(sql, *params)

        if row is None:
            raise NotFoundError(f"Pipeline {pipeline_id} not found")
        return _row_to_pipeline_response(dict(row))
    finally:
        await conn.close()


@router.patch("/{pipeline_id}", response_model=PipelineListItem)
async def patch_pipeline(pipeline_id: UUID, body: PatchPipelineRequest) -> PipelineListItem:
    # is_active only gates automatic triggers; it is a setting, not an
    # edit, so it does not bump updated_at.
    conn = await get_connection()
    try:
        updated = await conn.fetchval(
            "UPDATE pipelines SET is_active = $1 WHERE id = $2 RETURNING id",
            body.is_active,
            pipeline_id,
        )
        if updated is None:
            raise NotFoundError(f"Pipeline {pipeline_id} not found")
        row = await conn.fetchrow(_LIST_SQL + " WHERE p.id = $1", pipeline_id)
        return _row_to_list_item(row)
    finally:
        await conn.close()


@router.delete("/{pipeline_id}", status_code=204)
async def delete_pipeline(pipeline_id: UUID) -> Response:
    """Hard delete. runs -> pipelines and block_executions -> runs are both
    ON DELETE CASCADE, so the pipeline's whole run history goes with it."""
    conn = await get_connection()
    try:
        async with conn.transaction():
            result = await conn.execute(
                "DELETE FROM pipelines WHERE id = $1", pipeline_id
            )

        # asyncpg returns "DELETE N" where N is the row count
        count = int(result.split()[-1])
        if count == 0:
            raise NotFoundError(f"Pipeline {pipeline_id} not found")
        return Response(status_code=204)
    finally:
        await conn.close()


@router.get("/{pipeline_id}/latest-outputs", response_model=dict[str, LatestBlockOutput])
async def get_latest_outputs(pipeline_id: UUID) -> dict[str, LatestBlockOutput]:
    conn = await get_connection()
    try:
        exists = await conn.fetchval("SELECT 1 FROM pipelines WHERE id = $1", pipeline_id)
        if exists is None:
            raise NotFoundError(f"Pipeline {pipeline_id} not found")
        latest = await fetch_latest_outputs(conn, pipeline_id)
        return {bid: LatestBlockOutput(**v) for bid, v in latest.items()}
    finally:
        await conn.close()


@router.get("/{pipeline_id}/runs", response_model=list[RunResponse])
async def get_pipeline_runs(pipeline_id: UUID) -> list[RunResponse]:
    conn = await get_connection()
    try:
        if await conn.fetchval("SELECT 1 FROM pipelines WHERE id = $1", pipeline_id) is None:
            raise NotFoundError(f"Pipeline {pipeline_id} not found")
        rows = await conn.fetch(
            """
            SELECT * FROM runs
            WHERE pipeline_id = $1 AND run_type != 'test'
            ORDER BY created_at DESC
            """,
            pipeline_id,
        )
        return [_row_to_run_response(dict(row)) for row in rows]
    finally:
        await conn.close()
