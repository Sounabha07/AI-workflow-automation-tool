import json
from uuid import UUID

import asyncpg
from fastapi import APIRouter
from fastapi.responses import Response

from db import get_connection
from app.api.models import (
    CreatePipelineRequest,
    UpdatePipelineRequest,
    PipelineResponse,
    PipelineListItem,
    RunResponse,
)

router = APIRouter()


def _parse_jsonb(v) -> dict:
    return json.loads(v) if isinstance(v, str) else (v or {})


def _row_to_pipeline_response(row: dict) -> PipelineResponse:
    return PipelineResponse(
        id=row["id"],
        name=row["name"],
        definition=_parse_jsonb(row["definition"]),
        is_template=row["is_template"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


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


@router.post("", status_code=201, response_model=PipelineResponse)
async def create_pipeline(body: CreatePipelineRequest) -> PipelineResponse:
    conn = await get_connection()
    try:
        async with conn.transaction():
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
        rows = await conn.fetch(
            "SELECT id, name, is_template, created_at, updated_at FROM pipelines ORDER BY created_at DESC"
        )
        return [
            PipelineListItem(
                id=row["id"],
                name=row["name"],
                is_template=row["is_template"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]
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
            raise ValueError(f"Pipeline {pipeline_id} not found")
        return _row_to_pipeline_response(dict(row))
    finally:
        await conn.close()


@router.put("/{pipeline_id}", response_model=PipelineResponse)
async def update_pipeline(
    pipeline_id: UUID, body: UpdatePipelineRequest
) -> PipelineResponse:
    if body.name is None and body.definition is None:
        raise ValueError("At least one of 'name' or 'definition' must be provided")

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
            raise ValueError(f"Pipeline {pipeline_id} not found")
        return _row_to_pipeline_response(dict(row))
    finally:
        await conn.close()


@router.delete("/{pipeline_id}", status_code=204)
async def delete_pipeline(pipeline_id: UUID) -> Response:
    conn = await get_connection()
    try:
        try:
            async with conn.transaction():
                result = await conn.execute(
                    "DELETE FROM pipelines WHERE id = $1", pipeline_id
                )
        except asyncpg.ForeignKeyViolationError:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=409,
                content={"detail": "Cannot delete a pipeline that has existing runs"},
            )

        # asyncpg returns "DELETE N" where N is the row count
        count = int(result.split()[-1])
        if count == 0:
            raise ValueError(f"Pipeline {pipeline_id} not found")
        return Response(status_code=204)
    finally:
        await conn.close()


@router.get("/{pipeline_id}/runs", response_model=list[RunResponse])
async def get_pipeline_runs(pipeline_id: UUID) -> list[RunResponse]:
    conn = await get_connection()
    try:
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
