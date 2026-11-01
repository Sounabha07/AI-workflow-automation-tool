"""Manual check: crash recovery against the real stack. Not run in CI.

    docker compose exec worker python scripts/recovery_drill.py

Must run inside the worker container: the blocks call a slow local server this
script starts, and the last drill kills the worker's child processes. Creates
its own pipelines (name prefix recovery_drill_) and deletes them at the end.
"""

import asyncio
import http.server
import json
import os
import signal
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine  # noqa: E402
from db import get_connection  # noqa: E402
from tasks import execute_block_task, sweep_stuck_blocks  # noqa: E402

PORT = 18765
SLOW_SECONDS = 4
hits: dict[str, int] = {}
failures: list[str] = []


class SlowHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        hits[self.path] = hits.get(self.path, 0) + 1
        time.sleep(SLOW_SECONDS)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *args):
        pass


def check(name: str, passed: bool, detail="") -> None:
    print(f"{'PASS' if passed else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not passed else ""))
    if not passed:
        failures.append(name)


def blk(type_, next_, depends_on, config=None):
    return {"type": type_, "config": config or {}, "depends_on": depends_on, "next": next_}


def http_blk(next_, depends_on, path):
    return blk("http_request", next_, depends_on, {"method": "GET", "url": f"http://127.0.0.1:{PORT}/{path}"})


async def seed_run(name: str, definition: dict, statuses: dict[str, str], ready_at=True) -> str:
    """Creates a run directly, so nothing is queued unless the drill does it."""
    conn = await get_connection()
    try:
        pipeline_id = await conn.fetchval(
            "INSERT INTO pipelines (name, definition) VALUES ($1, $2) RETURNING id",
            f"recovery_drill_{name}",
            json.dumps(definition),
        )
        count = len(definition["blocks"])
        run_id = await conn.fetchval(
            "INSERT INTO runs (pipeline_id, pipeline_snapshot, input_data, total_blocks, blocks_remaining, "
            "status, started_at) VALUES ($1, $2, '{}', $3, $3, 'running', NOW()) RETURNING id",
            pipeline_id,
            json.dumps(definition),
            count,
        )
        for block_id, b in definition["blocks"].items():
            status = statuses.get(block_id, "pending")
            await conn.execute(
                "INSERT INTO block_executions (run_id, block_id, block_type, status, remaining_deps, ready_at) "
                "VALUES ($1, $2, $3, $4, $5, CASE WHEN $6::boolean THEN NOW() END)",
                run_id,
                block_id,
                b["type"],
                status,
                len(b["depends_on"]),
                ready_at and status == "ready",
            )
        return str(run_id)
    finally:
        await conn.close()


async def fetch_blocks(run_id: str) -> dict:
    conn = await get_connection()
    try:
        rows = await conn.fetch("SELECT * FROM block_executions WHERE run_id = $1", run_id)
        return {r["block_id"]: dict(r) for r in rows}
    finally:
        await conn.close()


async def fetch_run(run_id: str) -> dict:
    conn = await get_connection()
    try:
        return dict(await conn.fetchrow("SELECT * FROM runs WHERE id = $1", run_id))
    finally:
        await conn.close()


async def execute(sql: str, *args) -> None:
    conn = await get_connection()
    try:
        await conn.execute(sql, *args)
    finally:
        await conn.close()


async def wait_finished(run_id: str, timeout: float = 90) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = (await fetch_run(run_id))["status"]
        if status != "running":
            return status
        await asyncio.sleep(1)
    return "still running"


async def cleanup() -> None:
    await execute("DELETE FROM pipelines WHERE name LIKE 'recovery_drill_%'")


async def drill_finish_twice() -> None:
    print("\n1. Finishing a block twice counts once, including at a join")
    definition = {"blocks": {
        "a": blk("manual_trigger", ["c"], []),
        "b": blk("manual_trigger", ["c"], []),
        "c": blk("manual_trigger", [], ["a", "b"]),
    }}
    run_id = await seed_run("finish_twice", definition, {"a": "running", "b": "running"})

    await engine.handle_block_success(run_id, "a", {"n": 1})
    await engine.handle_block_success(run_id, "a", {"n": 2})
    await engine.handle_block_failure(run_id, "a", "late failure", False, 1)
    blocks = await fetch_blocks(run_id)
    run = await fetch_run(run_id)
    check("the join still waits for its other input", blocks["c"]["remaining_deps"] == 1, blocks["c"]["remaining_deps"])
    check("the join did not start", blocks["c"]["status"] == "pending", blocks["c"]["status"])
    check("the run counter dropped once", run["blocks_remaining"] == 2, run["blocks_remaining"])
    check("the first result is kept", json.loads(blocks["a"]["output"]) == {"n": 1}, blocks["a"]["output"])
    check("a late failure doesn't fail the run", run["status"] == "running", run["status"])


async def drill_sweeper_requeues() -> None:
    print("\n2. The sweeper recovers a ready block with no task behind it")
    definition = {"blocks": {
        "a": http_blk(["b"], [], "sweep_a"),
        "b": blk("manual_trigger", [], ["a"]),
    }}
    run_id = await seed_run("sweep", definition, {"a": "ready"})
    await engine.sweep_stuck_blocks()
    blocks = await fetch_blocks(run_id)
    check("a recently ready block is left alone", blocks["a"]["status"] == "ready" and "/sweep_a" not in hits)

    await execute(
        "UPDATE block_executions SET ready_at = NOW() - interval '10 minutes' WHERE run_id = $1", run_id
    )
    sweep_stuck_blocks.delay()
    status = await wait_finished(run_id)
    check("the run completes after the sweep", status == "succeeded", status)
    check("the block ran once", hits.get("/sweep_a") == 1, hits.get("/sweep_a"))


async def drill_duplicate_delivery() -> None:
    print("\n3. Two simultaneous deliveries run the block once")
    definition = {"blocks": {"a": http_blk([], [], "dupe")}}
    run_id = await seed_run("dupe", definition, {"a": "ready"})
    execute_block_task.delay(run_id, "a")
    execute_block_task.delay(run_id, "a")
    status = await wait_finished(run_id)
    check("the run succeeds", status == "succeeded", status)
    check("the block ran once", hits.get("/dupe") == 1, hits.get("/dupe"))
    run = await fetch_run(run_id)
    check("the run counter is exactly zero", run["blocks_remaining"] == 0, run["blocks_remaining"])


async def drill_abandoned() -> None:
    print("\n4. Old stuck rows fail instead of running again")
    old_ready = await seed_run("old_ready", {"blocks": {"a": http_blk([], [], "old")}}, {"a": "ready"}, ready_at=False)
    old_running = await seed_run("old_running", {"blocks": {"a": http_blk([], [], "old")}}, {"a": "running"})
    await execute(
        "UPDATE block_executions SET started_at = NOW() - interval '3 hours' WHERE run_id = $1", old_running
    )
    await engine.sweep_stuck_blocks()
    for name, run_id in (("ready with no ready_at", old_ready), ("running for over 2 hours", old_running)):
        run = await fetch_run(run_id)
        check(f"{name}: run failed", run["status"] == "failed", run["status"])
        message = (json.loads(run["error_summary"] or "{}")).get("message", "")
        check(f"{name}: message explains why", "worker crashed" in message, message)
    await asyncio.sleep(2)
    check("the old block did not run", "/old" not in hits, hits.get("/old"))


def worker_children() -> list[int]:
    """Celery's pool processes: celery processes whose parent is also celery."""
    me = os.getpid()
    procs: dict[int, int] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == me:
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                if b"celery" not in f.read():
                    continue
            with open(f"/proc/{entry}/stat") as f:
                procs[int(entry)] = int(f.read().rsplit(")", 1)[1].split()[1])
        except OSError:
            continue
    return [pid for pid, parent in procs.items() if parent in procs]


async def drill_worker_killed() -> None:
    print("\n5. A worker killed in the middle of a block gets its task back")
    definition = {"blocks": {
        "a": http_blk(["b"], [], "killed"),
        "b": blk("manual_trigger", [], ["a"]),
    }}
    run_id = await seed_run("killed", definition, {"a": "ready"})
    execute_block_task.delay(run_id, "a")

    deadline = time.time() + 30
    while "/killed" not in hits and time.time() < deadline:
        await asyncio.sleep(0.1)
    check("the block started", "/killed" in hits)

    children = worker_children()
    check("found the worker's child processes", bool(children))
    for pid in children:
        os.kill(pid, signal.SIGKILL)

    status = await wait_finished(run_id)
    check("the run completes after the kill", status == "succeeded", status)
    check("the block ran again (the known limit)", hits.get("/killed") == 2, hits.get("/killed"))
    run = await fetch_run(run_id)
    check("the run counter is exactly zero", run["blocks_remaining"] == 0, run["blocks_remaining"])


async def main() -> int:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), SlowHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        await drill_finish_twice()
        await drill_sweeper_requeues()
        await drill_duplicate_delivery()
        await drill_abandoned()
        await drill_worker_killed()
    finally:
        server.shutdown()
        await cleanup()

    print(f"\n{'All drills passed.' if not failures else f'{len(failures)} check(s) failed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
