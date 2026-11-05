"""
Tool definitions on http_request blocks, and how tool blocks are wired.

A block listed in an agent's `tools` is not a DAG node: the scheduler never
runs it, it gets no block_executions row and doesn't count in total_blocks.
The agent calls it. Its config's {{ }} references resolve when the agent
runs, so for validation they count as the agent's references.
"""

import json
import re
from typing import Any

from app.llm.base import ToolSpec

AGENT_TYPE = "agent"
FINISH_TOOL = "finish"

# Gemini allows a-z A-Z 0-9 _ : . - up to 128 (FunctionDeclaration.name);
# this is the stricter rule from the design, so it always fits.
TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MIN_DESCRIPTION_CHARS = 20
SIDE_EFFECT_CHOICES = ("auto", "true", "false")
SAFE_METHODS = ("GET", "HEAD")

# Keywords Gemini's Schema object documents (https://ai.google.dev/api/caching#Schema).
# Anything else in a tool's parameters may be ignored by the model.
GEMINI_SCHEMA_KEYWORDS = {
    "type", "format", "title", "description", "nullable", "enum", "items", "maxItems",
    "minItems", "properties", "required", "minProperties", "maxProperties", "minimum",
    "maximum", "minLength", "maxLength", "pattern", "example", "anyOf", "propertyOrdering",
    "default",
}


def _load(value: Any) -> Any:
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def agent_tool_ids(block_def: dict) -> list[str]:
    tools = (block_def.get("config") or {}).get("tools")
    if not isinstance(tools, list):
        return []
    return [t for t in tools if isinstance(t, str)]


def tool_owners(definition: dict) -> dict[str, list[str]]:
    """tool block id -> the agents that list it (more than one is invalid)."""
    owners: dict[str, list[str]] = {}
    for block_id, b in (definition.get("blocks") or {}).items():
        if isinstance(b, dict) and b.get("type") == AGENT_TYPE:
            for t in agent_tool_ids(b):
                owners.setdefault(t, []).append(block_id)
    return owners


def tool_block_ids(definition: dict) -> set[str]:
    """Blocks that are tools of some agent, and so not DAG nodes."""
    return set(tool_owners(definition))


def tool_parameters(config: dict) -> Any:
    params = _load(config.get("tool_parameters"))
    return {"type": "object", "properties": {}} if params in (None, "", {}) else params


def static_fields(config: dict) -> Any:
    value = _load(config.get("tool_static_fields"))
    return {} if value in (None, "") else value


def side_effects(config: dict) -> bool:
    choice = str(config.get("tool_side_effects") or "auto").lower()
    if choice == "true":
        return True
    if choice == "false":
        return False
    return str(config.get("method") or "GET").upper() not in SAFE_METHODS


def tool_spec(config: dict) -> ToolSpec:
    return ToolSpec(
        name=str(config.get("tool_name") or "").strip(),
        description=str(config.get("tool_description") or "").strip(),
        parameters=tool_parameters(config),
    )


def schema_problem(schema: Any) -> str | None:
    """Why `schema` can't be a tool's parameters, or None if it can."""
    if not isinstance(schema, dict):
        return "must be a JSON object"
    if schema.get("type") != "object":
        return 'must have "type": "object"'
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as e:
        return f"is not a valid JSON Schema: {e.message}"
    return None


def unsupported_keywords(schema: Any, path: str = "") -> list[str]:
    """Paths of keywords Gemini doesn't document, for a warning."""
    found: list[str] = []
    if not isinstance(schema, dict):
        return found
    for key, value in schema.items():
        here = f"{path}.{key}" if path else key
        if key not in GEMINI_SCHEMA_KEYWORDS and key != "$schema":
            found.append(here)
            continue
        if key == "properties" and isinstance(value, dict):
            for prop, sub in value.items():
                found += unsupported_keywords(sub, f"{here}.{prop}")
        elif key == "items":
            found += unsupported_keywords(value, here)
        elif key == "anyOf" and isinstance(value, list):
            for i, sub in enumerate(value):
                found += unsupported_keywords(sub, f"{here}[{i}]")
    return found


def definition_problems(tool_id: str, config: Any) -> list[str]:
    """Checks a tool block's definition section (not its wiring)."""
    if not isinstance(config, dict):
        return [f"Tool '{tool_id}': 'config' must be an object."]
    problems: list[str] = []
    name = str(config.get("tool_name") or "").strip()
    if not name:
        problems.append(f"Tool '{tool_id}': it needs a tool name.")
    elif not TOOL_NAME_PATTERN.match(name):
        problems.append(
            f"Tool '{tool_id}': tool name '{name}' must be letters, digits and underscores, "
            f"starting with a letter or _ (max 64)."
        )
    elif name == FINISH_TOOL:
        problems.append(f"Tool '{tool_id}': '{FINISH_TOOL}' is reserved for the agent's final answer.")
    description = str(config.get("tool_description") or "").strip()
    if len(description) < MIN_DESCRIPTION_CHARS:
        problems.append(
            f"Tool '{tool_id}': the description must be at least {MIN_DESCRIPTION_CHARS} characters. "
            f"It's what tells the model when and how to use the tool."
        )
    problem = schema_problem(tool_parameters(config))
    if problem:
        problems.append(f"Tool '{tool_id}': parameters {problem}.")
    fields = static_fields(config)
    if not isinstance(fields, dict):
        problems.append(f"Tool '{tool_id}': static fields must be a JSON object.")
    if str(config.get("tool_side_effects") or "auto").lower() not in SIDE_EFFECT_CHOICES:
        problems.append(f"Tool '{tool_id}': side effects must be auto, true or false.")
    return problems
