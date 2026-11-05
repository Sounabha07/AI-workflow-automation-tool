"""
The agent's checkpoint: one agent_steps row per model turn and per tool call.

Every write is its own committed statement, so a row survives a worker crash
the moment the call returns. A retry of the agent block reads these rows back
to rebuild the transcript and carry on (app/agent/loop.py).

step_index goes up by one per model call attempt (failed ones included); the
tool calls a model turn asked for share its step_index and are told apart by
tool_call_id.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


@dataclass
class StepRow:
    step_index: int
    kind: str  # "model" | "tool"
    status: str  # "started" | "completed" | "failed"
    tool_call_id: str | None = None
    tool_name: str | None = None
    side_effects: bool | None = None
    args: Any = None
    result: Any = None
    error: str | None = None
    provider_payload: Any = None
    usage: dict | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Set by the loop, not stored: written by an earlier attempt of the block.
    from_earlier_attempt: bool = False
    extra: dict = field(default_factory=dict)


class StepStore(Protocol):
    async def load(self, run_id: str, block_id: str) -> list[StepRow]: ...

    async def insert(self, run_id: str, block_id: str, row: StepRow) -> None: ...

    async def finish(
        self, run_id: str, block_id: str, step_index: int, tool_call_id: str | None,
        status: str, result: Any = None, error: str | None = None,
    ) -> None: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dump(v: Any) -> str | None:
    return None if v is None else json.dumps(v, default=str)


def _load(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


class PostgresStepStore:
    async def _conn(self):
        from db import get_connection

        return await get_connection()

    async def load(self, run_id: str, block_id: str) -> list[StepRow]:
        conn = await self._conn()
        try:
            rows = await conn.fetch(
                """
                SELECT step_index, kind, status, tool_call_id, tool_name, side_effects, args,
                       result, error, provider_payload, usage, started_at, finished_at
                FROM agent_steps WHERE run_id = $1 AND block_id = $2
                ORDER BY step_index, (kind = 'tool'), started_at, tool_call_id
                """,
                uuid.UUID(str(run_id)), block_id,
            )
        finally:
            await conn.close()
        return [
            StepRow(
                step_index=r["step_index"], kind=r["kind"], status=r["status"],
                tool_call_id=r["tool_call_id"], tool_name=r["tool_name"], side_effects=r["side_effects"],
                args=_load(r["args"]), result=_load(r["result"]), error=r["error"],
                provider_payload=_load(r["provider_payload"]), usage=_load(r["usage"]),
                started_at=r["started_at"], finished_at=r["finished_at"],
            )
            for r in rows
        ]

    async def insert(self, run_id: str, block_id: str, row: StepRow) -> None:
        conn = await self._conn()
        try:
            # A repeat (same step written by a redelivered task) is ignored.
            await conn.execute(
                """
                INSERT INTO agent_steps (id, run_id, block_id, step_index, kind, tool_call_id, tool_name,
                    status, side_effects, args, result, error, provider_payload, usage, started_at, finished_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                        COALESCE($15, now()), $16)
                ON CONFLICT (run_id, block_id, step_index, tool_call_id) DO NOTHING
                """,
                uuid.uuid4(), uuid.UUID(str(run_id)), block_id, row.step_index, row.kind, row.tool_call_id,
                row.tool_name, row.status, row.side_effects, _dump(row.args), _dump(row.result), row.error,
                _dump(row.provider_payload), _dump(row.usage), row.started_at, row.finished_at,
            )
        finally:
            await conn.close()

    async def finish(self, run_id, block_id, step_index, tool_call_id, status, result=None, error=None) -> None:
        conn = await self._conn()
        try:
            await conn.execute(
                """
                UPDATE agent_steps SET status = $5, result = $6, error = $7, finished_at = now()
                WHERE run_id = $1 AND block_id = $2 AND step_index = $3
                  AND tool_call_id IS NOT DISTINCT FROM $4
                """,
                uuid.UUID(str(run_id)), block_id, step_index, tool_call_id, status, _dump(result), error,
            )
        finally:
            await conn.close()


class MemoryStepStore:
    """For unit tests and the in-process paths that don't need persistence."""

    def __init__(self):
        self.rows: dict[tuple, StepRow] = {}

    async def load(self, run_id, block_id) -> list[StepRow]:
        rows = [r for (rid, bid, *_), r in self.rows.items() if (rid, bid) == (run_id, block_id)]
        rows.sort(key=lambda r: (r.step_index, r.kind != "model", r.started_at or _now(), r.tool_call_id or ""))
        return [StepRow(**{**r.__dict__, "extra": {}}) for r in rows]

    async def insert(self, run_id, block_id, row: StepRow) -> None:
        key = (run_id, block_id, row.step_index, row.tool_call_id)
        if key not in self.rows:
            self.rows[key] = StepRow(**{**row.__dict__, "started_at": row.started_at or _now()})

    async def finish(self, run_id, block_id, step_index, tool_call_id, status, result=None, error=None) -> None:
        row = self.rows.get((run_id, block_id, step_index, tool_call_id))
        if row:
            row.status, row.result, row.error, row.finished_at = status, result, error, _now()
