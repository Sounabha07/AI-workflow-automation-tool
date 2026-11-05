"""
POST /tools/test: one tool call through the agent's own request builder,
with no agent and no model. For the editor's "Test tool" button.

The tool block's {{ }} references resolve against the latest succeeded
outputs of the blocks upstream of its agent (as a test step would), when a
pipeline_id is given.
"""

import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from app.agent.http_tool import call_tool
from app.agent.loop import schema_errors
from app.agent.tools import definition_problems, side_effects, tool_owners, tool_parameters
from app.api.routes_pipelines import fetch_latest_outputs
from app.validation import InvalidWorkflowError, ancestors
from blocks.agent import LIMITS
from blocks.registry import get_block_class
from db import get_connection
from engine.resolver import resolve, structure_json_fields

router = APIRouter()


class TestToolRequest(BaseModel):
    definition: dict
    block_id: str
    args: dict = {}
    pipeline_id: UUID | None = None


@router.post("/test")
async def test_tool(body: TestToolRequest) -> dict[str, Any]:
    blocks = body.definition.get("blocks") if isinstance(body.definition, dict) else None
    block = (blocks or {}).get(body.block_id)
    if not isinstance(block, dict):
        raise ValueError(f"Block '{body.block_id}' isn't in the definition.")
    if block.get("type") != "http_request":
        raise ValueError(f"'{body.block_id}' is a {block.get('type')} block; only HTTP Request blocks are tools.")

    config = block.get("config") or {}
    problems = definition_problems(body.block_id, config)
    if problems:
        raise InvalidWorkflowError(problems)
    arg_errors = schema_errors(tool_parameters(config), body.args)
    if arg_errors:
        raise InvalidWorkflowError([f"Sample args: {e}" for e in arg_errors])

    run_state: dict = {}
    agent = (tool_owners(body.definition).get(body.block_id) or [None])[0]
    if body.pipeline_id is not None and agent is not None:
        conn = await get_connection()
        try:
            latest = await fetch_latest_outputs(conn, body.pipeline_id, ("succeeded",))
        finally:
            await conn.close()
        upstream = ancestors(body.definition, agent)
        run_state = {bid: v["output"] for bid, v in latest.items() if bid in upstream and v["output"] is not None}

    schema = getattr(get_block_class("http_request"), "schema", {})
    resolved = resolve(structure_json_fields(config, schema), run_state)

    started = time.monotonic()
    result = await call_tool(
        resolved, body.args,
        timeout_seconds=float(LIMITS["tool_timeout_seconds"][0]),
        max_result_chars=int(LIMITS["max_tool_result_chars"][0]),
    )
    return {
        "ok": result.ok,
        "request": result.request,
        "response": result.response,
        "result": result.full_result,
        "error": result.error,
        "status": result.status,
        "side_effects": side_effects(resolved),
        "attempts": result.attempts,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
