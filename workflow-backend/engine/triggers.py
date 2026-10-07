"""
pipeline_triggers: a derived index of each pipeline's schedule and webhook
trigger blocks (and pipeline_wait_links, one fixed resume link per wait
block). The definition stays the source of truth; sync_triggers()
rewrites both on pipeline create and update, on_activated() runs on
activation, and pipeline delete cascades.

fire_due_schedules() is the beat task body that starts scheduled runs.
"""

import json
import logging
import secrets
from datetime import datetime, timezone

from blocks import WAIT_TYPE
from blocks.schedule_trigger import DEFAULT_TIMEZONE, next_occurrence
from db import get_connection

logger = logging.getLogger(__name__)

INDEXED_TYPES = {"schedule_trigger": "schedule", "webhook_trigger": "webhook"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def sync_triggers(conn, pipeline_id, definition: dict) -> None:
    """Call inside the transaction that saves the definition. A webhook
    keeps its token across saves; a schedule's next_run_at is recomputed
    from now (never backfilled)."""
    wanted = {
        bid: b for bid, b in (definition.get("blocks") or {}).items()
        if isinstance(b, dict) and b.get("type") in INDEXED_TYPES
    }
    await conn.execute(
        "DELETE FROM pipeline_triggers WHERE pipeline_id = $1 AND NOT (block_id = ANY($2::text[]))",
        pipeline_id,
        list(wanted),
    )
    await _sync_wait_links(conn, pipeline_id, definition)
    for block_id, b in wanted.items():
        config = b.get("config") or {}
        if b["type"] == "webhook_trigger":
            await conn.execute(
                """
                INSERT INTO pipeline_triggers (pipeline_id, block_id, type, webhook_token)
                VALUES ($1, $2, 'webhook', $3)
                ON CONFLICT (pipeline_id, block_id) DO UPDATE SET
                    type = 'webhook',
                    webhook_token = COALESCE(pipeline_triggers.webhook_token, EXCLUDED.webhook_token),
                    cron_expr = NULL, timezone = NULL, next_run_at = NULL
                """,
                pipeline_id,
                block_id,
                secrets.token_urlsafe(24),
            )
        else:
            cron = config.get("cron")
            tz = config.get("timezone") or DEFAULT_TIMEZONE
            await conn.execute(
                """
                INSERT INTO pipeline_triggers (pipeline_id, block_id, type, cron_expr, timezone, next_run_at)
                VALUES ($1, $2, 'schedule', $3, $4, $5)
                ON CONFLICT (pipeline_id, block_id) DO UPDATE SET
                    type = 'schedule', webhook_token = NULL,
                    cron_expr = EXCLUDED.cron_expr, timezone = EXCLUDED.timezone,
                    next_run_at = EXCLUDED.next_run_at
                """,
                pipeline_id,
                block_id,
                cron,
                tz,
                next_occurrence(cron, tz, _now()),
            )


async def _sync_wait_links(conn, pipeline_id, definition: dict) -> None:
    """One fixed resume link per wait_for_input block, kept across saves."""
    wait_ids = [
        bid for bid, b in (definition.get("blocks") or {}).items()
        if isinstance(b, dict) and b.get("type") == WAIT_TYPE
    ]
    await conn.execute(
        "DELETE FROM pipeline_wait_links WHERE pipeline_id = $1 AND NOT (block_id = ANY($2::text[]))",
        pipeline_id,
        wait_ids,
    )
    for block_id in wait_ids:
        await conn.execute(
            "INSERT INTO pipeline_wait_links (pipeline_id, block_id, token) VALUES ($1, $2, $3) "
            "ON CONFLICT (pipeline_id, block_id) DO NOTHING",
            pipeline_id,
            block_id,
            secrets.token_urlsafe(24),
        )


async def backfill_wait_links() -> None:
    """Gives wait blocks saved before fixed links existed their link. Idempotent."""
    conn = await get_connection()
    try:
        rows = await conn.fetch(
            "SELECT id, definition FROM pipelines WHERE definition::text LIKE '%wait_for_input%'"
        )
        for r in rows:
            definition = r["definition"]
            async with conn.transaction():
                await _sync_wait_links(conn, r["id"], json.loads(definition) if isinstance(definition, str) else definition)
    finally:
        await conn.close()


async def list_wait_links(conn, pipeline_id) -> list[dict]:
    """[{block_id, url}] for API responses."""
    from engine.resolver import resume_url

    rows = await conn.fetch(
        "SELECT block_id, token FROM pipeline_wait_links WHERE pipeline_id = $1 ORDER BY block_id",
        pipeline_id,
    )
    return [{"block_id": r["block_id"], "url": resume_url(r["token"])} for r in rows]


async def on_activated(conn, pipeline_id) -> None:
    """The pipeline was just switched on: schedules restart from now, so
    time spent inactive never causes a burst of runs."""
    rows = await conn.fetch(
        "SELECT id, cron_expr, timezone FROM pipeline_triggers "
        "WHERE pipeline_id = $1 AND type = 'schedule'",
        pipeline_id,
    )
    now = _now()
    for r in rows:
        await conn.execute(
            "UPDATE pipeline_triggers SET next_run_at = $2 WHERE id = $1",
            r["id"],
            next_occurrence(r["cron_expr"], r["timezone"], now),
        )


async def set_pipeline_active(conn, pipeline_id, is_active: bool) -> bool | None:
    """PATCH is_active, inside the caller's transaction. Returns the previous
    value, or None if there is no such pipeline. Switching a pipeline on
    recomputes its schedules from now."""
    was = await conn.fetchval(
        "SELECT is_active FROM pipelines WHERE id = $1 FOR UPDATE", pipeline_id
    )
    if was is None:
        return None
    await conn.execute("UPDATE pipelines SET is_active = $2 WHERE id = $1", pipeline_id, is_active)
    if not was and is_active:
        await on_activated(conn, pipeline_id)
    return was


async def fire_due_schedules(limit: int = 50) -> list[str]:
    """Beat task body. In one transaction: lock due schedule rows of active
    pipelines (SKIP LOCKED, so concurrent ticks split the work instead of
    doubling it), create a run for each, and advance next_run_at to the
    next occurrence after NOW. However long beat was down, a trigger fires
    once. Runs are dispatched after commit. Returns the new run ids."""
    import engine

    conn = await get_connection()
    created: list[engine.CreatedRun] = []
    try:
        async with conn.transaction():
            due = await conn.fetch(
                """
                SELECT t.id, t.pipeline_id, t.cron_expr, t.timezone, t.next_run_at
                FROM pipeline_triggers t
                JOIN pipelines p ON p.id = t.pipeline_id
                WHERE t.type = 'schedule' AND p.is_active AND t.next_run_at <= NOW()
                ORDER BY t.next_run_at
                LIMIT $1
                FOR UPDATE OF t SKIP LOCKED
                """,
                limit,
            )
            for t in due:
                fired_at = _now()
                scheduled_for = t["next_run_at"].astimezone(timezone.utc).isoformat()
                try:
                    async with conn.transaction():  # savepoint: one bad row can't block the rest
                        run = await engine.create_run(
                            conn,
                            str(t["pipeline_id"]),
                            trigger_type="schedule",
                            trigger_payload={"scheduled_for": scheduled_for, "fired_at": fired_at.isoformat()},
                            trigger_id=t["id"],
                            # Belt and braces: one run per trigger per slot.
                            dedupe_key=f"schedule:{scheduled_for}",
                        )
                    created.append(run)
                except Exception:
                    logger.exception("Scheduled run for trigger %s failed to start", t["id"])

                try:
                    next_run_at = next_occurrence(t["cron_expr"], t["timezone"], fired_at)
                except ValueError:
                    logger.exception("Trigger %s has an unusable schedule; disabling it", t["id"])
                    next_run_at = None
                await conn.execute(
                    "UPDATE pipeline_triggers SET next_run_at = $2, last_fired_at = $3 WHERE id = $1",
                    t["id"],
                    next_run_at,
                    fired_at,
                )
    finally:
        await conn.close()

    for run in created:
        engine.dispatch_run(run)
    return [r.run_id for r in created if r.created]


async def list_triggers(conn, pipeline_ids: list) -> dict[str, list[dict]]:
    """pipeline_id -> its indexed triggers, for API responses."""
    from engine.resolver import public_url

    rows = await conn.fetch(
        "SELECT pipeline_id, block_id, type, webhook_token, cron_expr, timezone, next_run_at, last_fired_at "
        "FROM pipeline_triggers WHERE pipeline_id = ANY($1::uuid[]) ORDER BY block_id",
        pipeline_ids,
    )
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(str(r["pipeline_id"]), []).append({
            "block_id": r["block_id"],
            "type": r["type"],
            "webhook_url": public_url(f"/hooks/{r['webhook_token']}") if r["webhook_token"] else None,
            "cron": r["cron_expr"],
            "timezone": r["timezone"],
            "next_run_at": r["next_run_at"],
            "last_fired_at": r["last_fired_at"],
        })
    return out
