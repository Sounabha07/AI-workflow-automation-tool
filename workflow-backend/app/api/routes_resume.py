from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import engine
from db import get_connection
from app.errors import NotFoundError
from app.api.models import ResumeRequest, ResumeResponse

router = APIRouter()


@router.post("/{token}", response_model=ResumeResponse)
async def resume_block(token: UUID, body: ResumeRequest) -> ResumeResponse:
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT run_id, block_id, status
            FROM block_executions
            WHERE correlation_token = $1
            """,
            token,
        )
    finally:
        await conn.close()

    if row is None:
        raise NotFoundError(f"No block execution found for token {token}")

    if row["status"] != "waiting":
        return JSONResponse(
            status_code=409,
            content={
                "detail": f"Block execution is in status '{row['status']}', not 'waiting'"
            },
        )

    await engine.handle_block_success(
        str(row["run_id"]), row["block_id"], body.result_data
    )

    return ResumeResponse(
        block_id=row["block_id"],
        run_id=row["run_id"],
        status="resumed",
    )
