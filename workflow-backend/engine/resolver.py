"""
Minimal resolver: substitutes {{block_id.field.nested}} placeholders
in a config dict with real values from upstream block outputs.
"""

import json
import re
from typing import Any

from db import get_connection

PLACEHOLDER = re.compile(r"\{\{(.*?)\}\}")


def _lookup(path: str, run_state: dict) -> Any:
    segments = path.strip().split(".")
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
    whole = PLACEHOLDER.fullmatch(text)
    if whole:
        return _lookup(whole.group(1), run_state)

    # placeholder(s) embedded in surrounding text — stringify
    def replace(m):
        return str(_lookup(m.group(1), run_state))

    return PLACEHOLDER.sub(replace, text)


def resolve(value: Any, run_state: dict) -> Any:
    if isinstance(value, dict):
        return {k: resolve(v, run_state) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(item, run_state) for item in value]
    if isinstance(value, str):
        return _resolve_string(value, run_state)
    return value


async def build_run_state(run_id: str) -> dict:
    """Reads every finished block's output for this run from the DB."""
    conn = await get_connection()
    try:
        rows = await conn.fetch(
            """
            SELECT block_id, output
            FROM block_executions
            WHERE run_id = $1 AND output IS NOT NULL
            """,
            run_id,
        )
        return {
            r["block_id"]: (
                json.loads(r["output"])
                if isinstance(r["output"], str)
                else r["output"]
            )
            for r in rows
        }
    finally:
        await conn.close()
