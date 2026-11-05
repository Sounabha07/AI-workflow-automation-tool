import blocks.manual_trigger    # noqa: F401
import blocks.schedule_trigger  # noqa: F401
import blocks.webhook_trigger   # noqa: F401
import blocks.input_block       # noqa: F401
import blocks.http_request      # noqa: F401
import blocks.switch            # noqa: F401
import blocks.wait_for_input    # noqa: F401
import blocks.llm               # noqa: F401
import blocks.agent             # noqa: F401

from fastapi import APIRouter
from blocks.registry import list_registered_types, get_block_class
from app.api.models import BlockSchemaResponse

router = APIRouter()


@router.get("", response_model=list[BlockSchemaResponse])
async def list_blocks() -> list[BlockSchemaResponse]:
    result = []
    for block_type in list_registered_types():
        cls = get_block_class(block_type)
        schema = getattr(cls, "schema", {})
        result.append(
            BlockSchemaResponse.model_validate(
                {"type": block_type, "schema": schema,
                 "usable_as_tool": getattr(cls, "usable_as_tool", False)}
            )
        )
    return result
