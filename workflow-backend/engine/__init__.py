"""
The core DAG dispatch logic: readiness, the atomic decrement, and the
propagate rule — whenever a block completes, check its list of next
blocks; if a dependent's remaining_deps hits zero after decrementing, it
goes into the processing queue. Processing a queued block decides
whether to dispatch it for real execution or skip it (cascading), based
on whether ALL of its dependencies were skipped.
"""

import json

from db import get_connection


async def start_run(
    pipeline_id: str,
    run_type: str = "production",
    input_data: dict = None
) -> str:
    """Reads the pipeline definition FROM THE DATABASE (never passed in
    directly), creates the run + all its block_execution rows with
    correctly seeded remaining_deps, and dispatches whatever is
    immediately ready."""
    conn = await get_connection()
    try:
        pipeline = await conn.fetchrow(
            "SELECT definition FROM pipelines WHERE id = $1", pipeline_id
        )
        if pipeline is None:
            raise ValueError(f"No pipeline with id {pipeline_id}")

        definition = pipeline["definition"]
        if isinstance(definition, str):
            definition = json.loads(definition)
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
                if block_def["type"] == "input_block":
                    block_def = dict(block_def)
                    block_def["config"] = {
                        **block_def.get("config", {}),
                        "values": input_data or {}
                    }

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
    from engine.resolver import build_run_state, resolve

    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT be.block_type, r.pipeline_snapshot
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

        snapshot = row["pipeline_snapshot"]
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        block_def = snapshot["blocks"][block_id]
        raw_config = block_def.get("config", {})
    finally:
        await conn.close()

    # build run_state from every finished upstream block's output
    run_state = await build_run_state(run_id)

    # substitute any {{block_id.field}} placeholders with real values
    resolved_config = resolve(raw_config, run_state)

    return {
        "block_type": row["block_type"],
        "config": resolved_config,
    }


async def mark_running(run_id: str, block_id: str) -> None:
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE block_executions SET status = 'running', started_at = NOW() "
            "WHERE run_id = $1 AND block_id = $2",
            run_id,
            block_id,
        )
    finally:
        await conn.close()


async def _decrement_run_counter(conn, run_id: str) -> None:
    remaining = await conn.fetchval(
        "UPDATE runs SET blocks_remaining = blocks_remaining - 1 WHERE id = $1 RETURNING blocks_remaining",
        run_id,
    )
    if remaining == 0:
        await conn.execute(
            "UPDATE runs SET status = 'succeeded', finished_at = NOW() WHERE id = $1 AND status != 'failed'",
            run_id,
        )


async def _decrement_and_collect_ready(conn, run_id: str, dependent_ids: list) -> list:
    """THE atomic decrement. Exactly one caller sees a given dependent
    hit zero, even under real concurrency — see the celery-poc Proof 4."""
    ready = []
    for dep_id in dependent_ids:
        new_count = await conn.fetchval(
            "UPDATE block_executions SET remaining_deps = remaining_deps - 1 "
            "WHERE run_id = $1 AND block_id = $2 RETURNING remaining_deps",
            run_id,
            dep_id,
        )
        if new_count == 0:
            ready.append(dep_id)
    return ready


async def _resolve_ready_block(conn, run_id: str, block_id: str, snapshot: dict) -> str:
    """A block's remaining_deps just hit zero. Decide: dispatch for real
    execution, or skip it (because every dependency that could have fed
    it a real value was itself skipped)?"""
    depends_on = snapshot["blocks"][block_id].get("depends_on", [])
    if not depends_on:
        return "dispatch"
    rows = await conn.fetch(
        "SELECT status FROM block_executions WHERE run_id = $1 AND block_id = ANY($2::text[])",
        run_id,
        depends_on,
    )
    all_skipped = all(r["status"] == "skipped" for r in rows)
    return "skip" if all_skipped else "dispatch"


async def _skip_block(conn, run_id: str, block_id: str) -> None:
    await conn.execute(
        "UPDATE block_executions SET status = 'skipped', finished_at = NOW() "
        "WHERE run_id = $1 AND block_id = $2",
        run_id,
        block_id,
    )
    await _decrement_run_counter(conn, run_id)


async def _propagate_from(conn, run_id: str, snapshot: dict, source_block_id: str, to_dispatch: list) -> None:
    """source_block_id just reached a terminal state (already persisted
    as succeeded or skipped). Decrement its dependents; for each one
    that becomes ready, decide dispatch vs skip, recursing on skips."""
    next_field = snapshot["blocks"][source_block_id].get("next", [])
    dependent_ids = next_field if isinstance(next_field, list) else []

    ready_ids = await _decrement_and_collect_ready(conn, run_id, dependent_ids)
    for rid in ready_ids:
        action = await _resolve_ready_block(conn, run_id, rid, snapshot)
        if action == "dispatch":
            to_dispatch.append(rid)
        else:
            await _skip_block(conn, run_id, rid)
            await _propagate_from(conn, run_id, snapshot, rid, to_dispatch)


async def handle_block_success(run_id: str, block_id: str, output: dict) -> None:
    conn = await get_connection()
    to_dispatch = []
    try:
        async with conn.transaction():
            await conn.execute(
                "UPDATE block_executions SET status = 'succeeded', output = $1, finished_at = NOW() "
                "WHERE run_id = $2 AND block_id = $3",
                json.dumps(output),
                run_id,
                block_id,
            )
            await _decrement_run_counter(conn, run_id)

            snapshot_raw = await conn.fetchval("SELECT pipeline_snapshot FROM runs WHERE id = $1", run_id)
            snapshot = json.loads(snapshot_raw) if isinstance(snapshot_raw, str) else snapshot_raw
            next_field = snapshot["blocks"][block_id].get("next", [])

            if isinstance(next_field, dict):
                # Conditional block: pick the taken branch, skip the rest.
                branch = output.get("branch_taken")
                taken_ids = next_field.get(branch, [])
                untaken_ids = [bid for b, ids in next_field.items() if b != branch for bid in ids]

                ready = await _decrement_and_collect_ready(conn, run_id, taken_ids)
                for rid in ready:
                    action = await _resolve_ready_block(conn, run_id, rid, snapshot)
                    if action == "dispatch":
                        to_dispatch.append(rid)
                    else:
                        await _skip_block(conn, run_id, rid)
                        await _propagate_from(conn, run_id, snapshot, rid, to_dispatch)

                for skip_id in untaken_ids:
                    await _skip_block(conn, run_id, skip_id)
                    await _propagate_from(conn, run_id, snapshot, skip_id, to_dispatch)
            else:
                await _propagate_from(conn, run_id, snapshot, block_id, to_dispatch)
    finally:
        await conn.close()

    from tasks import execute_block_task

    for bid in to_dispatch:
        execute_block_task.delay(run_id, bid)


async def handle_block_failure(run_id: str, block_id: str, error_message: str) -> None:
    """Run-wide failure rule: any block failure, retries exhausted,
    fails the ENTIRE run, no exceptions."""
    conn = await get_connection()
    try:
        async with conn.transaction():
            await conn.execute(
                "UPDATE block_executions SET status = 'failed', error = $1, finished_at = NOW() "
                "WHERE run_id = $2 AND block_id = $3",
                json.dumps({"message": error_message}),
                run_id,
                block_id,
            )
            await _decrement_run_counter(conn, run_id)
            await conn.execute(
                "UPDATE runs SET status = 'failed', error_summary = $1, finished_at = NOW() "
                "WHERE id = $2 AND status != 'failed'",
                json.dumps({"block_id": block_id, "message": error_message}),
                run_id,
            )
    finally:
        await conn.close()
