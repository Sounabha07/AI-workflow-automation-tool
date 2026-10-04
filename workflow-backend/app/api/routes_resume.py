import json

from fastapi import APIRouter, HTTPException, Request

import engine
from app.api.body import read_limited_body
from app.api.models import ResumeResponse

router = APIRouter()

# Why a resume didn't happen -> (status code, message).
_REFUSALS = {
    "not_found": (404, "No wait block has this resume token."),
    "not_waiting": (409, "This block isn't waiting for input yet."),
    "already_resumed": (409, "This block was already resumed."),
    "gone": (410, "This block is no longer waiting: it timed out, or its run failed or was cancelled."),
}


@router.post("/{token}", response_model=ResumeResponse)
async def resume_block(token: str, request: Request) -> ResumeResponse:
    """Completes a waiting Wait for Input block. The body is any JSON object
    (empty allowed, max 1 MB); it becomes the block's output `data`. The
    token is the credential, so like /hooks this stays public."""
    raw = await read_limited_body(request)
    if raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Body is not valid JSON: {e}")
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Body must be a JSON object.")
    else:
        data = {}

    result = await engine.resume_waiting_block(token, data)
    if result.outcome != "resumed":
        code, message = _REFUSALS[result.outcome]
        raise HTTPException(status_code=code, detail=message)
    return ResumeResponse(run_id=result.run_id, block_id=result.block_id, status=result.status)
