"""
Minimal resolver: substitutes {{block_id.field.nested}} placeholders
in a config dict with real values from upstream block outputs.
"""

import json
import re
from typing import Any

from db import get_connection

PLACEHOLDER = re.compile(r"\{\{(.*?)\}\}")
# Exactly one placeholder and nothing else (surrounding whitespace allowed).
# The lazy PLACEHOLDER.fullmatch would also match "{{ a }} x {{ b }}".
WHOLE_PLACEHOLDER = re.compile(r"\s*\{\{([^{}]*)\}\}\s*")


def _lookup(path: str, run_state: dict) -> Any:
    path = path.strip()
    segments = path.split(".")
    block_id, *field_path = segments

    if block_id not in run_state:
        available = sorted(run_state.keys())
        raise ValueError(
            f"Reference '{{{{ {path} }}}}' — block '{block_id}' has no output "
            f"in this run yet. Blocks with output: {available}"
        )

    current = run_state[block_id]
    walked = block_id
    for segment in field_path:
        if not isinstance(current, dict) or segment not in current:
            available = sorted(current.keys()) if isinstance(current, dict) else []
            raise ValueError(
                f"Reference '{{{{ {path} }}}}' — path stopped at "
                f"'{walked}.{segment}'. "
                f"Available fields on '{walked}': {available}"
            )
        current = current[segment]
        walked += f".{segment}"

    return current


def _resolve_string(text: str, run_state: dict) -> Any:
    # whole string is exactly one placeholder — preserve real type
    whole = WHOLE_PLACEHOLDER.fullmatch(text)
    if whole:
        return _lookup(whole.group(1), run_state)

    # placeholder(s) embedded in surrounding text — stringify. Non-strings use
    # JSON (true, {"a": 1}) rather than Python's repr (True, {'a': 1}).
    def replace(m):
        value = _lookup(m.group(1), run_state)
        return value if isinstance(value, str) else json.dumps(value)

    return PLACEHOLDER.sub(replace, text)


def parse_json_template(text: str) -> Any:
    """Parses a JSON body template into a structure. Placeholders outside a
    JSON string are quoted first, so '{"n": {{ a.count }}}' becomes
    {"n": "{{ a.count }}"}; resolve() then keeps each exact-placeholder value's
    real type. Raises ValueError if the text isn't a valid template."""
    out: list[str] = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\":
                out.append(text[i + 1:i + 2])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if text.startswith("{{", i):
            end = text.find("}}", i + 2)
            if end == -1:
                raise ValueError("Unclosed {{ in JSON body")
            out.append(json.dumps(text[i:end + 2]))
            i = end + 2
            continue
        out.append(ch)
        i += 1
    try:
        return json.loads("".join(out))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON body is not valid JSON: {e}") from e


def structure_json_fields(config: dict, schema: dict) -> dict:
    """Turns json-typed fields stored as template text into structures before
    resolution, so they are resolved value by value, not as one string."""
    json_fields = {f["name"] for f in schema.get("fields", []) if f.get("type") == "json"}
    out = dict(config)
    for name in json_fields:
        value = out.get(name)
        if isinstance(value, str) and value.strip():
            out[name] = parse_json_template(value)
    return out


def resolve(value: Any, run_state: dict) -> Any:
    if isinstance(value, dict):
        return {k: resolve(v, run_state) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(item, run_state) for item in value]
    if isinstance(value, str):
        return _resolve_string(value, run_state)
    return value


async def build_run_state(run_id: str) -> dict:
    """Starts from runs.seed_outputs (test-step runs only), then overlays
    every finished block's output for this run from the DB."""
    conn = await get_connection()
    try:
        seed = await conn.fetchval("SELECT seed_outputs FROM runs WHERE id = $1", run_id)
        state = (json.loads(seed) if isinstance(seed, str) else seed) or {}
        rows = await conn.fetch(
            """
            SELECT block_id, output
            FROM block_executions
            WHERE run_id = $1 AND output IS NOT NULL
            """,
            run_id,
        )
        state.update({
            r["block_id"]: (
                json.loads(r["output"])
                if isinstance(r["output"], str)
                else r["output"]
            )
            for r in rows
        })
        return state
    finally:
        await conn.close()
