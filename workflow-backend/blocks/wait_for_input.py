"""
Wait for Input — pauses its branch until someone POSTs to its resume URL.

The block never sleeps. When dispatched, execute() only validates the
config; the Celery task then parks the block in status 'waiting' with a
deadline and returns, freeing the worker. POST /resume/{token} completes
it (output {data, resumed_at}); the beat task sweep_wait_timeouts fails it
once the deadline passes. Upstream blocks can include the link through
{{ resume.<block_id>.url }} (or .token), which is not a dependency edge.
"""

from typing import Any

from blocks.base import BaseBlock, FatalError
from blocks.registry import register_block

MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 604800  # 7 days


def timeout_problem(value: Any) -> str | None:
    """Why value isn't a usable timeout_seconds, or None if it is."""
    if value is None or value == "":
        return "timeout_seconds is required."
    if isinstance(value, bool):
        return "timeout_seconds must be a whole number of seconds."
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "timeout_seconds must be a whole number of seconds."
    if seconds != int(seconds):
        return "timeout_seconds must be a whole number of seconds."
    if not MIN_TIMEOUT_SECONDS <= seconds <= MAX_TIMEOUT_SECONDS:
        return f"timeout_seconds must be between {MIN_TIMEOUT_SECONDS} and {MAX_TIMEOUT_SECONDS}."
    return None


@register_block("wait_for_input")
class WaitForInputBlock(BaseBlock):
    # Tells the task to park the block as 'waiting' instead of completing it.
    waits_for_input = True
    # Config errors won't fix themselves, and a timeout is final.
    max_retries = 0

    schema = {
        "name": "Wait for Input",
        "category": "Flow",
        "description": "Pause until someone posts JSON to this block's resume URL. "
                       "Times out and fails the run after the timeout.",
        "fields": [
            {"name": "timeout_seconds", "label": "Timeout (seconds)", "type": "number",
             "required": True, "default": 3600,
             "description": f"Fail the run if nobody resumes it in time ({MIN_TIMEOUT_SECONDS} "
                            f"to {MAX_TIMEOUT_SECONDS})."},
            {"name": "description", "label": "Description", "type": "string",
             "description": "What the person resuming this should send."},
        ],
    }

    async def execute(
        self,
        config: dict[str, Any],
        input_data: dict[str, Any],
        credentials: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        problem = timeout_problem(config.get("timeout_seconds"))
        if problem:
            raise FatalError(f"Wait for Input block: {problem}")
        return {"timeout_seconds": int(float(config["timeout_seconds"]))}
