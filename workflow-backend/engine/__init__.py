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

Wait-for-input blocks park in status 'waiting' without holding a worker.
resume_waiting_block() and the timeout sweep each claim the block with a
conditional UPDATE (status = 'waiting'), so exactly one of them wins.

Tasks are delivered at least once, so finishing a block is safe to repeat:
only the first finish counts. Queuing isn't transactional, so a block can
end up 'ready' with no task behind it; sweep_stuck_blocks recovers those.
"""

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import NamedTuple

import events
from blocks import TRIGGER_TYPES, WAIT_TYPE
from db import get_connection

logger = logging.getLogger(__name__)

MASK = "••••••••"

# How long a 'ready' block waits for a worker before it is queued again.
READY_STALE_SECONDS = 300
# Longer than Redis's default 1-hour redelivery window, so a task lost with
# its worker has had its chance to come back before the run is failed.
RUNNING_STALE_SECONDS = 7200

_NOT_FINISHED = "status NOT IN ('succeeded', 'failed', 'skipped', 'cancelled')"


def _load_json(v):
    return json.loads(v) if isinstance(v, str) else v


def _outgoing_edges(block_def: dict) -> list[tuple[str, str | None]]:
    """(target, output_name) pairs. output_name is None for non-switch blocks."""
    nxt = block_def.get("next", [])
    if isinstance(nxt, dict):
        return [(t, output) for output, targets in nxt.items() for t in targets]
    return [(t, None) for t in nxt]


def _block_event(
    block_id: str, status: str, retry_count: int = 0, error: dict | None = None, **extra
) -> dict:
    return {
        "type": "block_status",
        "block_id": block_id,
        "status": status,
        "retry_count": retry_count,
        "error": error,
        **extra,
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


def dispatch(run_id: str, block_ids: list[str]) -> None:
    """Queues blocks whose state is already committed. A failure is only
    logged: the blocks stay 'ready' and sweep_stuck_blocks queues them again."""
    from tasks import execute_block_task

    for block_id in block_ids:
        try:
            execute_block_task.delay(run_id, block_id)
        except Exception:
            logger.exception("Could not queue block %s of run %s", block_id, run_id)


def mask_sensitive(config: dict, schema: dict) -> dict:
    """Copy of config with every schema field marked sensitive replaced by MASK."""
    sensitive = {f["name"] for f in schema.get("fields", []) if f.get("sensitive")}
    return {k: (MASK if k in sensitive and v not in (None, "") else v) for k, v in config.items()}


class RunVanishedError(Exception):
    """The run (or this block's row in it) no longer exists: its pipeline was
    deleted mid-run, cascading to the run. Nothing is left to do."""


class PipelineInactiveError(Exception):
    """An automatic trigger fired for a pipeline whose is_active is off."""


class CreatedRun(NamedTuple):
    run_id: str
    pipeline_id: str
    ready_block_ids: list[str]
    # False when dedupe_key matched an earlier run: nothing was created and
    # run_id is that earlier run.
    created: bool


async def insert_block_execution(
    conn, run_id, block_id: str, block_type: str, status: str, remaining_deps: int
) -> None:
    """The one place block_executions rows are created, so every
    wait_for_input row gets its resume_token when its run is created."""
    await conn.execute(
        """
        INSERT INTO block_executions (run_id, block_id, block_type, status, remaining_deps, resume_token, ready_at)
        VALUES ($1, $2, $3, $4, $5, $6, CASE WHEN $7::boolean THEN NOW() END)
        """,
        run_id,
        block_id,
        block_type,
        status,
        remaining_deps,
        secrets.token_urlsafe(32) if block_type == WAIT_TYPE else None,
        status == "ready",
    )


async def create_run(
    conn,
    pipeline_id: str,
    input_data: dict | None = None,
    run_type: str = "production",
    trigger_type: str = "manual",
    trigger_payload=None,
    trigger_id=None,
    dedupe_key: str | None = None,
    *,
    activate: bool = False,
    require_active: bool = False,
) -> CreatedRun:
    """Creates the run and all its block_execution rows with correctly
    seeded remaining_deps. Runs inside the caller's transaction; pass the
    result to dispatch_run() AFTER commit.

    Reads the pipeline definition FROM THE DATABASE (never passed in
    directly) and freezes it as pipeline_snapshot. Manual runs are always
    allowed; automatic triggers pass require_active=True and get
    PipelineInactiveError if the pipeline is off. With activate=True the
    pipeline is also switched on (never off here)."""
    pipeline = await conn.fetchrow(
        "SELECT definition, is_active FROM pipelines WHERE id = $1", pipeline_id
    )
    if pipeline is None:
        raise ValueError(f"No pipeline with id {pipeline_id}")
    if require_active and not pipeline["is_active"]:
        raise PipelineInactiveError(f"Pipeline {pipeline_id} is not active")

    from app.agent.tools import tool_block_ids

    definition = _load_json(pipeline["definition"])
    # Blocks wired to an agent's Tools port are called by the agent, never
    # scheduled: no block_executions row, not counted in total_blocks. They
    # stay in pipeline_snapshot, which the agent reads them from.
    tools = tool_block_ids(definition)
    blocks = {bid: b for bid, b in definition["blocks"].items() if bid not in tools}
    total_blocks = len(blocks)

    if activate and not pipeline["is_active"]:
        from engine.triggers import on_activated

        # Doesn't touch updated_at: activation is a setting, not an
        # edit (same as PATCH), so it never triggers stale-edit warnings.
        await conn.execute(
            "UPDATE pipelines SET is_active = TRUE WHERE id = $1 AND NOT is_active",
            pipeline_id,
        )
        await on_activated(conn, pipeline_id)

    run_id = await conn.fetchval(
        """
        INSERT INTO runs (pipeline_id, run_type, pipeline_snapshot,
                          input_data, total_blocks, blocks_remaining,
                          status, started_at, trigger_type, trigger_payload,
                          trigger_id, dedupe_key)
        VALUES ($1, $2, $3, $4, $5, $5, 'running', NOW(), $6, $7, $8, $9)
        ON CONFLICT (trigger_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING
        RETURNING id
        """,
        pipeline_id,
        run_type,
        json.dumps(definition),
        json.dumps(input_data or {}),
        total_blocks,
        trigger_type,
        None if trigger_payload is None else json.dumps(trigger_payload, default=str),
        trigger_id,
        dedupe_key,
    )
    if run_id is None:
        # The same delivery was seen before: hand back the run it created.
        existing = await conn.fetchval(
            "SELECT id FROM runs WHERE trigger_id = $1 AND dedupe_key = $2",
            trigger_id,
            dedupe_key,
        )
        return CreatedRun(str(existing), str(pipeline_id), [], False)

    ready_block_ids = []
    for block_id, block_def in blocks.items():
        remaining = len(block_def.get("depends_on", []))
        status = "ready" if remaining == 0 else "pending"
        await insert_block_execution(conn, run_id, block_id, block_def["type"], status, remaining)
        if remaining == 0:
            ready_block_ids.append(block_id)

    return CreatedRun(str(run_id), str(pipeline_id), ready_block_ids, True)


def dispatch_run(run: CreatedRun) -> None:
    """Call only AFTER the create_run transaction commits: enqueuing isn't
    transactional, and the worker must be able to see the rows."""
    if not run.created:
        return
    publish_run_started(run.run_id, run.pipeline_id)
    dispatch(run.run_id, run.ready_block_ids)


async def start_run(
    pipeline_id: str,
    input_data: dict | None = None,
    run_type: str = "production",
    trigger_type: str = "manual",
    trigger_payload=None,
    trigger_id=None,
    dedupe_key: str | None = None,
    *,
    activate: bool = False,
    require_active: bool = False,
) -> CreatedRun:
    """create_run() in its own transaction, then dispatch_run(). Used by
    the manual run route and the webhook route; the scheduler calls
    create_run() directly so the run commits with its trigger row update."""
    conn = await get_connection()
    try:
        async with conn.transaction():
            run = await create_run(
                conn, pipeline_id, input_data, run_type, trigger_type, trigger_payload,
                trigger_id, dedupe_key, activate=activate, require_active=require_active,
            )
    finally:
        await conn.close()
    dispatch_run(run)
    return run


async def claim_block(run_id: str, block_id: str, resuming: bool) -> bool:
    """Checked before every execution, and atomic so only one task can take a
    'ready' block. False means don't run it: the block is finished or another
    worker has it, or the run failed ('no new work starts after a failure') or
    no longer exists (its pipeline was deleted mid-run, cascading to the run).
    resuming is true for a retry or a redelivery, whose block is already
    'running' because this same task claimed it earlier."""
    conn = await get_connection()
    try:
        claimed = await conn.fetchval(
            """
            UPDATE block_executions be
            SET status = 'running', started_at = COALESCE(be.started_at, NOW())
            FROM runs r
            WHERE be.run_id = $1 AND be.block_id = $2
              AND r.id = be.run_id AND r.status = 'running'
              AND (be.status = 'ready' OR (be.status = 'running' AND $3::boolean))
            RETURNING be.id
            """,
            run_id,
            block_id,
            resuming,
        )
        return claimed is not None
    finally:
        await conn.close()


async def get_block_context(run_id: str, block_id: str) -> dict:
    """Raises ValueError when a {{ }} reference can't be resolved or the
    block's saved credential can't be used."""
    from app.credentials import CredentialError, credential_fields, load_block_credentials
    from blocks.registry import get_block_class
    from engine.resolver import build_run_state, resolve, structure_json_fields

    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT be.block_type, be.started_at, r.pipeline_snapshot, r.input_data, r.trigger_payload
            FROM block_executions be
            JOIN runs r ON r.id = be.run_id
            WHERE be.run_id = $1 AND be.block_id = $2
            """,
            run_id,
            block_id,
        )
        if row is None:
            raise RunVanishedError(
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
    # JSON fields are resolved structurally (see structure_json_fields).
    schema = getattr(get_block_class(row["block_type"]), "schema", {})
    resolved_config = resolve(structure_json_fields(raw_config, schema), run_state)

    # Input blocks receive the run's input_data as their values. Injected
    # after resolution so user-supplied values are never treated as templates.
    if row["block_type"] == "input_block":
        resolved_config = {**resolved_config, "values": _load_json(row["input_data"]) or {}}

    # Trigger blocks output the run's trigger_payload, passed as input_data
    # (not config) so it isn't copied into resolved_config.
    trigger_payload = None
    if row["block_type"] in TRIGGER_TYPES:
        trigger_payload = _load_json(row["trigger_payload"])

    # Saved credentials are decrypted here and travel separately from config,
    # so the secret never reaches resolved_config. The id comes from the raw
    # config: credential fields aren't templates.
    credentials = None
    if credential_fields(schema):
        conn = await get_connection()
        try:
            credentials = await load_block_credentials(conn, raw_config, schema)
        except CredentialError as e:
            raise ValueError(f"Credential error: {e}") from None
        finally:
            await conn.close()

    input_data = trigger_payload if isinstance(trigger_payload, dict) else {}

    # An agent's tools: each tool block's config, resolved against the same
    # run_state now. Passed in input_data, never config, so tool secrets
    # aren't stored in the agent's resolved_config.
    if row["block_type"] == "agent":
        tool_schema = getattr(get_block_class("http_request"), "schema", {})
        tools = {}
        for tool_id in raw_config.get("tools") or []:
            tool_def = snapshot["blocks"].get(tool_id)
            if tool_def is None:
                raise ValueError(f"Agent '{block_id}': tool block '{tool_id}' isn't in this workflow.")
            tools[tool_id] = resolve(
                structure_json_fields(tool_def.get("config") or {}, tool_schema), run_state
            )
        # The total timeout counts from the first attempt, which set started_at.
        input_data = {"tools": tools, "started_at": row["started_at"]}

    return {
        "block_type": row["block_type"],
        "config": resolved_config,
        "input_data": input_data,
        "credentials": credentials,
    }


async def mark_running(run_id: str, block_id: str, resolved_config: dict, schema: dict) -> bool:
    """Stores the resolved config with sensitive fields masked. Returns
    False, changing nothing, unless the block is still running (claim_block
    set that), so a stale task can't touch a waiting or finished block."""
    conn = await get_connection()
    try:
        retry_count = await conn.fetchval(
            "UPDATE block_executions SET resolved_config = $3 "
            "WHERE run_id = $1 AND block_id = $2 AND status = 'running' "
            "RETURNING retry_count",
            run_id,
            block_id,
            json.dumps(mask_sensitive(resolved_config, schema), default=str),
        )
    finally:
        await conn.close()
    if retry_count is None:
        return False
    events.publish(run_id, _block_event(block_id, "running", retry_count))
    return True


async def mark_waiting(run_id: str, block_id: str, timeout_seconds: int) -> None:
    """Parks a wait_for_input block until its deadline. The run stays
    running and dependents are untouched; the task returns right after."""
    from engine.resolver import resume_url

    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "UPDATE block_executions SET status = 'waiting', "
            "wait_deadline = NOW() + make_interval(secs => $3) "
            "WHERE run_id = $1 AND block_id = $2 AND status = 'running' "
            "RETURNING retry_count, resume_token, wait_deadline",
            run_id,
            block_id,
            float(timeout_seconds),
        )
    finally:
        await conn.close()
    if row is None:
        return
    events.publish(run_id, _block_event(
        block_id, "waiting", row["retry_count"],
        resume_url=resume_url(row["resume_token"]),
        wait_deadline=row["wait_deadline"].isoformat(),
    ))


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
                "UPDATE block_executions SET status = 'ready', ready_at = NOW() "
                "WHERE run_id = $1 AND block_id = $2",
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


async def _after_success(
    conn,
    run_id: str,
    block_id: str,
    output: dict,
    retry_count: int,
    to_dispatch: list,
    pending_events: list,
) -> None:
    """Everything that follows a block being marked succeeded (already
    persisted by the caller, in this same transaction): its event, edge
    propagation and the run counter. Shared by normal completion and resume."""
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


async def handle_block_success(run_id: str, block_id: str, output: dict) -> None:
    conn = await get_connection()
    to_dispatch: list[str] = []
    pending_events: list[dict] = []
    try:
        async with conn.transaction():
            # Every terminal transition (success, resume, failure) locks the
            # run row before any block row, so they can't deadlock each other.
            await conn.execute("SELECT 1 FROM runs WHERE id = $1 FOR UPDATE", run_id)
            # Only the first finish counts: a repeat must not touch the counters.
            retry_count = await conn.fetchval(
                f"UPDATE block_executions SET status = 'succeeded', output = $1, finished_at = NOW() "
                f"WHERE run_id = $2 AND block_id = $3 AND {_NOT_FINISHED} RETURNING retry_count",
                json.dumps(output, default=str),
                run_id,
                block_id,
            )
            if retry_count is None:
                return  # already finished, or the run was deleted while it executed
            await _after_success(
                conn, run_id, block_id, output, retry_count, to_dispatch, pending_events
            )
    finally:
        await conn.close()

    _publish_all(run_id, pending_events)
    dispatch(run_id, to_dispatch)


class ResumeResult(NamedTuple):
    # "resumed", or why not: "not_found", "not_waiting", "already_resumed", "gone".
    outcome: str
    run_id: str | None = None
    block_id: str | None = None
    status: str | None = None


async def resume_waiting_block(token: str, data: dict) -> ResumeResult:
    """POST /resume/{token}. One conditional UPDATE claims the block (still
    waiting, deadline not passed) and stores its output, then the normal
    success path runs in the same transaction. A racing timeout sweep or
    second resume finds status != 'waiting' and loses."""
    output = {"data": data, "resumed_at": datetime.now(timezone.utc).isoformat()}
    conn = await get_connection()
    to_dispatch: list[str] = []
    pending_events: list[dict] = []
    current = None
    try:
        async with conn.transaction():
            # Run row first: the lock order every terminal transition uses.
            await conn.fetchval(
                """
                SELECT r.id FROM runs r JOIN block_executions be ON be.run_id = r.id
                WHERE be.resume_token = $1 FOR UPDATE OF r
                """,
                token,
            )
            row = await conn.fetchrow(
                """
                UPDATE block_executions
                SET status = 'succeeded', output = $2, finished_at = NOW()
                WHERE resume_token = $1 AND status = 'waiting' AND wait_deadline > NOW()
                RETURNING run_id, block_id, retry_count
                """,
                token,
                json.dumps(output, default=str),
            )
            if row is not None:
                await _after_success(
                    conn, str(row["run_id"]), row["block_id"], output, row["retry_count"],
                    to_dispatch, pending_events,
                )
            else:
                current = await conn.fetchrow(
                    """
                    SELECT be.run_id, be.block_id, be.status::text AS status,
                           r.status::text AS run_status
                    FROM block_executions be JOIN runs r ON r.id = be.run_id
                    WHERE be.resume_token = $1
                    """,
                    token,
                )
    finally:
        await conn.close()

    if row is None:
        if current is None:
            return ResumeResult("not_found")
        status = current["status"]
        if status == "succeeded":
            outcome = "already_resumed"
        elif status in ("failed", "cancelled", "skipped", "waiting") or current["run_status"] == "failed":
            # Still 'waiting' here means past its deadline, about to be swept.
            outcome = "gone"
        else:
            outcome = "not_waiting"
        return ResumeResult(outcome, str(current["run_id"]), current["block_id"], status)

    run_id = str(row["run_id"])
    _publish_all(run_id, pending_events)
    dispatch(run_id, to_dispatch)
    return ResumeResult("resumed", run_id, row["block_id"], "succeeded")


async def resume_by_block_link(link_token: str, data: dict) -> ResumeResult | None:
    """POST to a wait block's fixed link (pipeline_wait_links): resumes the
    run that has waited longest at that block. None if link_token isn't a
    block link. Candidates are read unlocked, then claimed through
    resume_waiting_block (which keeps the run-row-first lock order); a
    candidate lost to a concurrent resume or timeout moves on to the next."""
    conn = await get_connection()
    try:
        link = await conn.fetchrow(
            "SELECT pipeline_id, block_id FROM pipeline_wait_links WHERE token = $1", link_token
        )
        if link is None:
            return None
        candidates = await conn.fetch(
            """
            SELECT be.resume_token
            FROM block_executions be JOIN runs r ON r.id = be.run_id
            WHERE r.pipeline_id = $1 AND be.block_id = $2
              AND be.status = 'waiting' AND be.wait_deadline > NOW()
            ORDER BY be.started_at, be.id
            LIMIT 20
            """,
            link["pipeline_id"],
            link["block_id"],
        )
    finally:
        await conn.close()

    for c in candidates:
        result = await resume_waiting_block(c["resume_token"], data)
        if result.outcome == "resumed":
            return result
    return ResumeResult("nothing_waiting", block_id=link["block_id"])


async def handle_block_failure(
    run_id: str,
    block_id: str,
    message: str,
    retryable: bool,
    attempts: int,
    from_status: str | None = None,
    detail: dict | None = None,
) -> bool:
    """Run-wide failure rule: any block failure, retries exhausted,
    fails the ENTIRE run, no exceptions. `retryable` is true only for an
    exhausted RetryableError. Wait blocks still waiting in the run are
    cancelled in the same transaction.

    With from_status, the block is failed only if it is still in that
    status (the timeout sweep's claim). Returns False if it wasn't."""
    conn = await get_connection()
    pending_events: list[dict] = []
    try:
        async with conn.transaction():
            # Run row first: the lock order every terminal transition uses.
            await conn.execute("SELECT 1 FROM runs WHERE id = $1 FOR UPDATE", run_id)
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
            if detail is not None:
                error["detail"] = detail
            retry_count = max(attempts - 1, 0)
            # Only the first finish counts: a repeat must not touch the counters.
            claimed = await conn.fetchval(
                f"UPDATE block_executions SET status = 'failed', error = $1, "
                f"is_retryable_error = $2, retry_count = $3, "
                f"started_at = COALESCE(started_at, NOW()), finished_at = NOW() "
                f"WHERE run_id = $4 AND block_id = $5 AND {_NOT_FINISHED} "
                f"AND ($6::text IS NULL OR status::text = $6) RETURNING 1",
                json.dumps(error, default=str),
                retryable,
                retry_count,
                run_id,
                block_id,
                from_status,
            )
            if claimed is None:
                return False
            # Events and the run summary leave the (possibly large) detail out.
            brief = {k: v for k, v in error.items() if k != "detail"}
            pending_events.append(_block_event(block_id, "failed", retry_count, brief))

            # Fail the run before decrementing, so a failing last block can
            # never flip the run to succeeded first.
            error_summary = {**brief, "block_id": block_id}
            pipeline_id = await conn.fetchval(
                "UPDATE runs SET status = 'failed', error_summary = $1, finished_at = NOW() "
                "WHERE id = $2 AND status != 'failed' RETURNING pipeline_id",
                json.dumps(error_summary),
                run_id,
            )
            cancelled = await conn.fetch(
                "UPDATE block_executions SET status = 'cancelled', finished_at = NOW() "
                "WHERE run_id = $1 AND status = 'waiting' RETURNING block_id",
                run_id,
            )
            pending_events.extend(_block_event(r["block_id"], "cancelled") for r in cancelled)
            if pipeline_id is not None:
                pending_events.append(_run_event(pipeline_id, "failed", error_summary))
            await _decrement_run_counter(conn, run_id, pending_events)
    finally:
        await conn.close()

    _publish_all(run_id, pending_events)
    return True


async def sweep_wait_timeouts(limit: int = 200) -> int:
    """Beat task body: fails every waiting block past its deadline, as a
    non-retryable error, through handle_block_failure. The SELECT only
    finds candidates; the conditional UPDATE in handle_block_failure is the
    claim, so concurrent sweeps and resumes never double-handle a block.
    Returns how many blocks this call failed."""
    conn = await get_connection()
    try:
        rows = await conn.fetch(
            """
            SELECT run_id, block_id, resolved_config->>'timeout_seconds' AS timeout_seconds
            FROM block_executions
            WHERE status = 'waiting' AND wait_deadline <= NOW()
            ORDER BY wait_deadline
            LIMIT $1
            """,
            limit,
        )
    finally:
        await conn.close()

    failed = 0
    for r in rows:
        seconds = r["timeout_seconds"]
        try:
            seconds = int(float(seconds))
        except (TypeError, ValueError):
            pass
        if await handle_block_failure(
            str(r["run_id"]), r["block_id"],
            f"Timed out waiting for input after {seconds} seconds",
            False, 1, from_status="waiting",
        ):
            failed += 1
    return failed


async def sweep_stuck_blocks() -> None:
    """Recovers what a crash or a queue failure left behind, in runs that are
    still 'running'. A block queued twice is harmless (claim_block), and a
    failed block that turns out to be alive can't finish twice."""
    conn = await get_connection()
    try:
        requeue = await conn.fetch(
            """
            UPDATE block_executions be
            SET ready_at = NOW()
            FROM runs r
            WHERE r.id = be.run_id AND r.status = 'running'
              AND be.status = 'ready'
              AND be.ready_at < NOW() - make_interval(secs => $1)
            RETURNING be.run_id, be.block_id
            """,
            float(READY_STALE_SECONDS),
        )
        # 'ready' with no ready_at predates this column. Those blocks are too
        # old to run now: their side effects would happen long after the fact.
        abandoned = await conn.fetch(
            """
            SELECT be.run_id, be.block_id, be.retry_count, be.status
            FROM block_executions be
            JOIN runs r ON r.id = be.run_id
            WHERE r.status = 'running'
              AND ((be.status = 'ready' AND be.ready_at IS NULL)
                OR (be.status = 'running'
                    AND COALESCE(be.started_at, be.created_at) < NOW() - make_interval(secs => $1)))
            """,
            float(RUNNING_STALE_SECONDS),
        )
    finally:
        await conn.close()

    for row in requeue:
        logger.warning("Requeuing stuck block %s of run %s", row["block_id"], row["run_id"])
        dispatch(str(row["run_id"]), [row["block_id"]])

    for row in abandoned:
        logger.warning("Failing stuck block %s of run %s", row["block_id"], row["run_id"])
        reason = "was never picked up" if row["status"] == "ready" else "stopped responding"
        await handle_block_failure(
            str(row["run_id"]),
            row["block_id"],
            f"This block {reason}, probably because a worker crashed. Run the workflow again.",
            False,
            row["retry_count"] + 1,
        )
