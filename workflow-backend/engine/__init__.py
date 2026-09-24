"""
The core DAG dispatch logic: readiness, the atomic decrement, and the
propagate rule, tracked per edge. Whenever a block reaches a terminal
state, every outgoing edge is either live (the source succeeded and, for
a switch, the edge hangs off the output named in branch_taken) or dead
(source skipped, or an untaken switch output). Each target's
remaining_deps is decremented and live_deps incremented for live edges in
one atomic statement. When remaining_deps hits zero the target is
dispatched if at least one edge into it was live, otherwise it is skipped
and its own edges propagate as dead, recursively, in the same transaction.
"""

import json

import events
from db import get_connection

MASK = "••••••••"


def _load_json(v):
    return json.loads(v) if isinstance(v, str) else v


def _outgoing_edges(block_def: dict) -> list[tuple[str, str | None]]:
    """(target, output_name) pairs. output_name is None for non-switch blocks."""
    nxt = block_def.get("next", [])
    if isinstance(nxt, dict):
        return [(t, output) for output, targets in nxt.items() for t in targets]
    return [(t, None) for t in nxt]


def _block_event(block_id: str, status: str, retry_count: int = 0, error: dict | None = None) -> dict:
    return {
        "type": "block_status",
        "block_id": block_id,
        "status": status,
        "retry_count": retry_count,
        "error": error,
    }


def _run_event(pipeline_id, status: str, error_summary: dict | None = None) -> dict:
    return {
        "type": "run_status",
        "pipeline_id": str(pipeline_id),
        "status": status,
        "error_summary": error_summary,
    }


def _publish_all(run_id: str, pending_events: list[dict]) -> None:
    for event in pending_events:
        events.publish(run_id, event)


def publish_run_started(run_id: str, pipeline_id) -> None:
    events.publish(run_id, _run_event(pipeline_id, "running"))


def mask_sensitive(config: dict, schema: dict) -> dict:
    """Copy of config with every schema field marked sensitive replaced by MASK."""
    sensitive = {f["name"] for f in schema.get("fields", []) if f.get("sensitive")}
    return {k: (MASK if k in sensitive and v not in (None, "") else v) for k, v in config.items()}


async def start_run(
    pipeline_id: str,
    run_type: str = "production",
    input_data: dict = None
) -> str:
    """Reads the pipeline definition FROM THE DATABASE (never passed in
    directly), creates the run + all its block_execution rows with
    correctly seeded remaining_deps, and dispatches whatever is
    immediately ready.

    Manual runs are always allowed. pipelines.is_active only gates
    automatic triggers (webhook, schedule), which must check it before
    calling this."""
    conn = await get_connection()
    try:
        pipeline = await conn.fetchrow(
            "SELECT definition FROM pipelines WHERE id = $1", pipeline_id
        )
        if pipeline is None:
            raise ValueError(f"No pipeline with id {pipeline_id}")

        definition = _load_json(pipeline["definition"])
        blocks = definition["blocks"]
        total_blocks = len(blocks)

        ready_block_ids = []
        async with conn.transaction():
            run_id = await conn.fetchval(
                """
                INSERT INTO runs (pipeline_id, run_type, pipeline_snapshot,
                                  input_data, total_blocks, blocks_remaining,
                                  status, started_at)
                VALUES ($1, $2, $3, $4, $5, $5, 'running', NOW())
                RETURNING id
                """,
                pipeline_id,
                run_type,
                json.dumps(definition),
                json.dumps(input_data or {}),
                total_blocks,
            )

            for block_id, block_def in blocks.items():
                depends_on = block_def.get("depends_on", [])
                remaining = len(depends_on)
                status = "ready" if remaining == 0 else "pending"
                await conn.execute(
                    """
                    INSERT INTO block_executions (run_id, block_id, block_type, status, remaining_deps)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    run_id,
                    block_id,
                    block_def["type"],
                    status,
                    remaining,
                )
                if remaining == 0:
                    ready_block_ids.append(block_id)
    finally:
        await conn.close()

    publish_run_started(str(run_id), pipeline_id)

    # Dispatch only AFTER commit — enqueuing isn't transactional.
    from tasks import execute_block_task

    for block_id in ready_block_ids:
        execute_block_task.delay(str(run_id), block_id)

    return str(run_id)


async def is_run_failed(run_id: str) -> bool:
    """Checked before every dispatch — the enforcement mechanism for
    'no new work starts after a failure'."""
    conn = await get_connection()
    try:
        status = await conn.fetchval("SELECT status FROM runs WHERE id = $1", run_id)
        return status == "failed"
    finally:
        await conn.close()


async def get_block_context(run_id: str, block_id: str) -> dict:
    """Raises ValueError when a {{ }} reference can't be resolved."""
    from engine.resolver import build_run_state, resolve

    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT be.block_type, r.pipeline_snapshot, r.input_data
            FROM block_executions be
            JOIN runs r ON r.id = be.run_id
            WHERE be.run_id = $1 AND be.block_id = $2
            """,
            run_id,
            block_id,
        )
        if row is None:
            raise RuntimeError(
                f"No block_execution for run_id={run_id}, block_id={block_id}"
            )

        snapshot = _load_json(row["pipeline_snapshot"])
        block_def = snapshot["blocks"][block_id]
        raw_config = block_def.get("config", {})
    finally:
        await conn.close()

    # build run_state from every finished upstream block's output
    run_state = await build_run_state(run_id)

    # substitute any {{block_id.field}} placeholders with real values
    resolved_config = resolve(raw_config, run_state)

    # Input blocks receive the run's input_data as their values. Injected
    # after resolution so user-supplied values are never treated as templates.
    if row["block_type"] == "input_block":
        resolved_config = {**resolved_config, "values": _load_json(row["input_data"]) or {}}

    return {
        "block_type": row["block_type"],
        "config": resolved_config,
    }


async def mark_running(run_id: str, block_id: str, resolved_config: dict, schema: dict) -> None:
    """Stores the resolved config with sensitive fields masked."""
    conn = await get_connection()
    try:
        retry_count = await conn.fetchval(
            "UPDATE block_executions SET status = 'running', "
            "started_at = COALESCE(started_at, NOW()), resolved_config = $3 "
            "WHERE run_id = $1 AND block_id = $2 RETURNING retry_count",
            run_id,
            block_id,
            json.dumps(mask_sensitive(resolved_config, schema), default=str),
        )
    finally:
        await conn.close()
    events.publish(run_id, _block_event(block_id, "running", retry_count or 0))


async def record_retry(run_id: str, block_id: str, retry_count: int) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE block_executions SET retry_count = $3 WHERE run_id = $1 AND block_id = $2",
            run_id,
            block_id,
            retry_count,
        )
    finally:
        await conn.close()
    events.publish(run_id, _block_event(block_id, "running", retry_count))


async def _decrement_run_counter(conn, run_id: str, pending_events: list) -> None:
    remaining = await conn.fetchval(
        "UPDATE runs SET blocks_remaining = blocks_remaining - 1 WHERE id = $1 RETURNING blocks_remaining",
        run_id,
    )
    if remaining == 0:
        pipeline_id = await conn.fetchval(
            "UPDATE runs SET status = 'succeeded', finished_at = NOW() "
            "WHERE id = $1 AND status != 'failed' RETURNING pipeline_id",
            run_id,
        )
        if pipeline_id is not None:
            pending_events.append(_run_event(pipeline_id, "succeeded"))


async def _propagate(
    conn,
    run_id: str,
    snapshot: dict,
    source_id: str,
    source_succeeded: bool,
    branch_taken: str | None,
    to_dispatch: list,
    pending_events: list,
) -> None:
    """source_id just reached a terminal state (already persisted). Walk
    its outgoing edges, decrementing each target; decide dispatch vs skip
    for any target whose remaining_deps hits zero, recursing on skips."""
    for target, output in _outgoing_edges(snapshot["blocks"][source_id]):
        live = source_succeeded and (output is None or output == branch_taken)
        row = await conn.fetchrow(
            """
            UPDATE block_executions
            SET remaining_deps = remaining_deps - 1,
                live_deps = live_deps + $3
            WHERE run_id = $1 AND block_id = $2
            RETURNING remaining_deps, live_deps
            """,
            run_id,
            target,
            1 if live else 0,
        )
        if row is None or row["remaining_deps"] != 0:
            continue

        if row["live_deps"] > 0:
            await conn.execute(
                "UPDATE block_executions SET status = 'ready' WHERE run_id = $1 AND block_id = $2",
                run_id,
                target,
            )
            to_dispatch.append(target)
        else:
            await conn.execute(
                "UPDATE block_executions SET status = 'skipped', finished_at = NOW() "
                "WHERE run_id = $1 AND block_id = $2",
                run_id,
                target,
            )
            pending_events.append(_block_event(target, "skipped"))
            await _decrement_run_counter(conn, run_id, pending_events)
            await _propagate(
                conn, run_id, snapshot, target, False, None, to_dispatch, pending_events
            )


async def handle_block_success(run_id: str, block_id: str, output: dict) -> None:
    conn = await get_connection()
    to_dispatch: list[str] = []
    pending_events: list[dict] = []
    try:
        async with conn.transaction():
            retry_count = await conn.fetchval(
                "UPDATE block_executions SET status = 'succeeded', output = $1, finished_at = NOW() "
                "WHERE run_id = $2 AND block_id = $3 RETURNING retry_count",
                json.dumps(output, default=str),
                run_id,
                block_id,
            )
            pending_events.append(_block_event(block_id, "succeeded", retry_count or 0))

            snapshot = _load_json(
                await conn.fetchval("SELECT pipeline_snapshot FROM runs WHERE id = $1", run_id)
            )
            branch_taken = output.get("branch_taken") if isinstance(output, dict) else None
            await _propagate(
                conn, run_id, snapshot, block_id, True, branch_taken, to_dispatch, pending_events
            )
            # Decrement last so the run_status event follows every block event.
            await _decrement_run_counter(conn, run_id, pending_events)
    finally:
        await conn.close()

    _publish_all(run_id, pending_events)

    from tasks import execute_block_task

    for bid in to_dispatch:
        execute_block_task.delay(run_id, bid)


async def handle_block_failure(
    run_id: str, block_id: str, message: str, retryable: bool, attempts: int
) -> None:
    """Run-wide failure rule: any block failure, retries exhausted,
    fails the ENTIRE run, no exceptions. `retryable` is true only for an
    exhausted RetryableError."""
    conn = await get_connection()
    pending_events: list[dict] = []
    try:
        async with conn.transaction():
            block_type = await conn.fetchval(
                "SELECT block_type FROM block_executions WHERE run_id = $1 AND block_id = $2",
                run_id,
                block_id,
            )
            error = {
                "message": message,
                "type": block_type,
                "attempts": attempts,
                "retryable": retryable,
            }
            retry_count = max(attempts - 1, 0)
            await conn.execute(
                "UPDATE block_executions SET status = 'failed', error = $1, "
                "is_retryable_error = $2, retry_count = $3, "
                "started_at = COALESCE(started_at, NOW()), finished_at = NOW() "
                "WHERE run_id = $4 AND block_id = $5",
                json.dumps(error),
                retryable,
                retry_count,
                run_id,
                block_id,
            )
            pending_events.append(_block_event(block_id, "failed", retry_count, error))

            # Fail the run before decrementing, so a failing last block can
            # never flip the run to succeeded first.
            error_summary = {**error, "block_id": block_id}
            pipeline_id = await conn.fetchval(
                "UPDATE runs SET status = 'failed', error_summary = $1, finished_at = NOW() "
                "WHERE id = $2 AND status != 'failed' RETURNING pipeline_id",
                json.dumps(error_summary),
                run_id,
            )
            if pipeline_id is not None:
                pending_events.append(_run_event(pipeline_id, "failed", error_summary))
            await _decrement_run_counter(conn, run_id, pending_events)
    finally:
        await conn.close()

    _publish_all(run_id, pending_events)
