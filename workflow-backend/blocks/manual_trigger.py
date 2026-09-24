from typing import Any
from blocks.base import BaseBlock
from blocks.registry import register_block


@register_block("manual_trigger")
class ManualTriggerBlock(BaseBlock):
    schema = {
        "name": "Manual Trigger",
        "description": "Starts the pipeline when triggered manually.",
        "fields": []
    }

    async def execute(
        self,
        config: dict[str, Any],
        input_data: dict[str, Any],
        credentials: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {}
