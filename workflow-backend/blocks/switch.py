"""
Switch Block — routes data down one of several named outputs.

Rules are evaluated in order; the first match wins. The engine reads
`branch_taken` from the output to decide which outgoing edges are live.
"""

from typing import Any

from blocks.base import BaseBlock, FatalError
from blocks.registry import register_block

OPERATORS = ("equals", "not_equals", "contains", "greater_than", "less_than", "is_empty")
FALLBACK = "fallback"


def switch_outputs(config: dict[str, Any]) -> list[str]:
    """Output names a switch exposes: rule outputs, plus fallback if enabled."""
    outputs = [str(r.get("output", "")) for r in config.get("rules") or [] if isinstance(r, dict)]
    if config.get("fallback", True):
        outputs.append(FALLBACK)
    return outputs


def _to_float(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _matches(operator: str, value: Any, compare_value: Any) -> bool:
    if operator == "is_empty":
        return value is None or value == "" or value == [] or value == {}

    if operator in ("greater_than", "less_than"):
        left, right = _to_float(value), _to_float(compare_value)
        if left is None or right is None:
            raise FatalError(
                f"Switch block: '{operator}' needs numbers on both sides, "
                f"got {value!r} and {compare_value!r}."
            )
        return left > right if operator == "greater_than" else left < right

    if operator in ("equals", "not_equals"):
        left, right = _to_float(value), _to_float(compare_value)
        if left is not None and right is not None:
            equal = left == right
        else:
            equal = str(value) == str(compare_value)
        return equal if operator == "equals" else not equal

    if operator == "contains":
        return str(compare_value) in str(value)

    raise FatalError(
        f"Switch block: unknown operator '{operator}'. "
        f"Use one of: {', '.join(OPERATORS)}."
    )


@register_block("switch")
class SwitchBlock(BaseBlock):
    schema = {
        "name": "Switch",
        "category": "Flow",
        "description": "Send data down different paths using rules.",
        "fields": [
            {"name": "value", "label": "Value to check", "type": "string", "required": True,
             "description": "Usually an expression, e.g. {{ github_info.data.stargazers_count }}"},
            {"name": "rules", "label": "Routing rules", "type": "switch_rules", "default": []},
            {"name": "fallback", "label": "Send everything else to a fallback output",
             "type": "boolean", "default": True},
        ],
    }

    async def execute(
        self,
        config: dict[str, Any],
        input_data: dict[str, Any],
        credentials: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        value = config.get("value")
        rules = config.get("rules") or []
        fallback = config.get("fallback", True)

        seen: set[str] = set()
        for rule in rules:
            output = str(rule.get("output", "")).strip()
            if not output:
                raise FatalError("Switch block: every rule needs an output name.")
            if output == FALLBACK:
                raise FatalError("Switch block: 'fallback' is reserved and can't be a rule output.")
            if output in seen:
                raise FatalError(f"Switch block: output name '{output}' is used more than once.")
            seen.add(output)

        for rule in rules:
            if _matches(rule.get("operator", ""), value, rule.get("compare_value", "")):
                return {"branch_taken": str(rule["output"]).strip(), "value": value}

        return {"branch_taken": FALLBACK if fallback else None, "value": value}
