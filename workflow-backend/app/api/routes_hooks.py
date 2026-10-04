import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import engine
from app.api.body import read_limited_body
from blocks.webhook_trigger import DEFAULT_SIGNATURE_HEADER, build_payload, verify_signature
from db import get_connection

logger = logging.getLogger(__name__)

router = APIRouter()

# Delivery ids that make a webhook idempotent, in order of preference.
DEDUPE_HEADERS = ("x-github-delivery", "idempotency-key")


@router.post("/{token}")
async def receive_webhook(token: str, request: Request) -> JSONResponse:
    """Starts a run of the workflow whose webhook trigger owns `token`.

    PUBLIC ROUTE: callers are third-party services, authenticated only by
    the unguessable token and the optional HMAC signature. When Firebase
    auth is added, this route (and /resume) must be exempt from it.

    202 {run_id} for a new run; 200 {run_id} for a repeated delivery id;
    404 unknown token; 413 body over 1 MB; 401 bad or missing signature;
    409 workflow inactive (no run is created)."""
    conn = await get_connection()
    try:
        trigger = await conn.fetchrow(
            """
            SELECT t.id, t.pipeline_id, t.block_id,
                   p.definition -> 'blocks' -> t.block_id -> 'config' AS config
            FROM pipeline_triggers t JOIN pipelines p ON p.id = t.pipeline_id
            WHERE t.webhook_token = $1 AND t.type = 'webhook'
            """,
            token,
        )
    finally:
        await conn.close()
    if trigger is None:
        raise HTTPException(status_code=404, detail="Unknown webhook.")

    raw = await read_limited_body(request)

    config = trigger["config"]
    config = (json.loads(config) if isinstance(config, str) else config) or {}
    signature_header = (config.get("signature_header") or "").strip() or DEFAULT_SIGNATURE_HEADER
    secret = config.get("secret")
    # Never log the secret or the signature.
    if secret and not verify_signature(secret, raw, request.headers.get(signature_header)):
        raise HTTPException(status_code=401, detail="Missing or invalid signature.")

    dedupe_key = next(
        (request.headers[h].strip() for h in DEDUPE_HEADERS if request.headers.get(h, "").strip()),
        None,
    )
    payload = build_payload(
        request.method, raw, dict(request.query_params), dict(request.headers), signature_header
    )
    try:
        run = await engine.start_run(
            str(trigger["pipeline_id"]),
            trigger_type="webhook",
            trigger_payload=payload,
            trigger_id=trigger["id"],
            dedupe_key=dedupe_key,
            require_active=True,
        )
    except engine.PipelineInactiveError:
        raise HTTPException(status_code=409, detail="This workflow is inactive.")

    return JSONResponse(status_code=202 if run.created else 200, content={"run_id": run.run_id})
