from typing import Any
from blocks.base import BaseBlock, FatalError
from blocks.registry import register_block


@register_block("input_block")
class InputBlock(BaseBlock):
    schema = {
        "name": "Input",
        "description": (
            "Defines input fields that the user fills in when "
            "triggering a run. Downstream blocks reference values via "
            "{{input_block.values.field_name}}."
        ),
        "fields": [
            {
                "name": "fields",
                "label": "Input Fields",
                "type": "field_definitions",
                "required": False,
                "default": [],
                "description": (
                    "Each field: name, label, "
                    "type (text|json), required, description."
                )
            }
        ]
    }

    async def execute(
        self,
        config: dict[str, Any],
        input_data: dict[str, Any],
        credentials: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        field_definitions = config.get("fields", [])
        values = config.get("values", {})

        for field_def in field_definitions:
            if field_def.get("required") and \
               field_def["name"] not in values:
                raise FatalError(
                    f"Input block: required field "
                    f"'{field_def['name']}' was not provided."
                )

        return {"values": values}
