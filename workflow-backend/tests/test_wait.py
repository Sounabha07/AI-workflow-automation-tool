"""Resume and timeout state transitions, against a scripted connection.
The real race (one conditional UPDATE wins) is exercised end to end by
scripts/smoke_test.py; here we pin what each outcome does and doesn't write."""

import pytest

import engine
from blocks.base import FatalError
from blocks.wait_for_input import MAX_TIMEOUT_SECONDS, WaitForInputBlock, timeout_problem
from tests.fakes import ScriptedConn

SNAPSHOT = {"blocks": {
    "wait": {"type": "wait_for_input", "next": ["after"], "depends_on": []},
    "after": {"type": "http_request", "next": [], "depends_on": ["wait"]},
}}


@pytest.fixture
def wire(monkeypatch):
    """Points the engine at a ScriptedConn and captures events and dispatches."""
    published, dispatched = [], []

    def install(conn):
        async def fake_get_connection():
            return conn

        monkeypatch.setattr(engine, "get_connection", fake_get_connection)
        monkeypatch.setattr(engine.events, "publish", lambda run_id, e: published.append(e))
        monkeypatch.setattr(engine, "dispatch", lambda run_id, ids: dispatched.extend(ids))
        return published, dispatched

    return install


@pytest.mark.parametrize("value,ok", [
    (1, True), (MAX_TIMEOUT_SECONDS, True), ("60", True), (30.0, True),
    (0, False), (MAX_TIMEOUT_SECONDS + 1, False), (-5, False), (None, False),
    ("", False), ("soon", False), (1.5, False), (True, False),
])
def test_timeout_bounds(value, ok):
    assert (timeout_problem(value) is None) is ok


async def test_wait_block_execute_validates_and_returns_timeout():
    assert await WaitForInputBlock().execute({"timeout_seconds": "90"}, {}) == {"timeout_seconds": 90}
    with pytest.raises(FatalError):
        await WaitForInputBlock().execute({"timeout_seconds": 0}, {})
    assert WaitForInputBlock.waits_for_input and WaitForInputBlock.max_retries == 0


async def test_resume_claims_and_runs_the_normal_success_path(wire):
    conn = ScriptedConn({
        "WHERE resume_token = $1 AND status = 'waiting'": {"run_id": "r1", "block_id": "wait", "retry_count": 0},
        "SELECT pipeline_snapshot": SNAPSHOT,
        "SET remaining_deps = remaining_deps - 1": {"remaining_deps": 0, "live_deps": 1},
        "SET blocks_remaining = blocks_remaining - 1": 1,
    })
    published, dispatched = wire(conn)

    result = await engine.resume_waiting_block("tok", {"x": 1})

    assert result == engine.ResumeResult("resumed", "r1", "wait", "succeeded")
    claim_query, claim_args = next(c for c in conn.calls if "resume_token = $1 AND status = 'waiting'" in c[0])
    assert "wait_deadline > NOW()" in claim_query  # a resume after the deadline can't win
    assert '"x": 1' in claim_args[1] and "resumed_at" in claim_args[1]
    assert conn.ran("FOR UPDATE OF r")  # run row locked before the block row
    assert dispatched == ["after"]
    assert [e["status"] for e in published] == ["succeeded"]


@pytest.mark.parametrize("status,run_status,outcome", [
    ("succeeded", "running", "already_resumed"),
    ("running", "running", "not_waiting"),
    ("pending", "running", "not_waiting"),
    ("pending", "failed", "gone"),
    ("failed", "failed", "gone"),  # timed out
    ("cancelled", "failed", "gone"),
    ("waiting", "running", "gone"),  # past its deadline, not swept yet
])
async def test_resume_refusals(wire, status, run_status, outcome):
    conn = ScriptedConn({
        "JOIN runs r ON r.id = be.run_id": {"run_id": "r1", "block_id": "wait",
                                             "status": status, "run_status": run_status},
    })
    published, dispatched = wire(conn)
    result = await engine.resume_waiting_block("tok", {})
    assert result.outcome == outcome
    assert not conn.ran("SELECT pipeline_snapshot") and not published and not dispatched


async def test_resume_unknown_token(wire):
    wire(ScriptedConn())
    assert (await engine.resume_waiting_block("nope", {})).outcome == "not_found"


async def test_timeout_claim_lost_to_a_resume_changes_nothing(wire):
    conn = ScriptedConn({"SELECT block_type": "wait_for_input"})  # claim UPDATE returns None
    published, _ = wire(conn)
    claimed = await engine.handle_block_failure("r1", "wait", "Timed out", False, 1, from_status="waiting")
    assert claimed is False
    assert not conn.ran("UPDATE runs SET status = 'failed'") and not published


async def test_timeout_claim_fails_run_and_cancels_other_waits(wire):
    conn = ScriptedConn({
        "SELECT block_type": "wait_for_input",
        "AND ($6::text IS NULL OR status::text = $6)": 1,
        "UPDATE runs SET status = 'failed'": "pipe-1",
        "SET status = 'cancelled'": [{"block_id": "other_wait"}],
    })
    published, _ = wire(conn)
    claimed = await engine.handle_block_failure(
        "r1", "wait", "Timed out waiting for input after 5 seconds", False, 1, from_status="waiting"
    )
    assert claimed is True
    claim_args = next(a for q, a in conn.calls if "AND ($6::text IS NULL" in q)
    assert claim_args[-1] == "waiting" and claim_args[1] is False  # non-retryable
    assert [(e["block_id"] if "block_id" in e else e["type"], e["status"]) for e in published] == [
        ("wait", "failed"), ("other_wait", "cancelled"), ("run_status", "failed"),
    ]


async def test_sweep_fails_each_expired_wait_with_the_timeout_message(monkeypatch, wire):
    conn = ScriptedConn({"wait_deadline <= NOW()": [
        {"run_id": "r1", "block_id": "w1", "timeout_seconds": "5"},
        {"run_id": "r2", "block_id": "w2", "timeout_seconds": "60"},
    ]})
    wire(conn)
    calls = []

    async def fake_failure(run_id, block_id, message, retryable, attempts, from_status=None):
        calls.append((run_id, block_id, message, retryable, from_status))
        return block_id == "w1"  # w2 was resumed in the meantime

    monkeypatch.setattr(engine, "handle_block_failure", fake_failure)
    assert await engine.sweep_wait_timeouts() == 1
    assert calls == [
        ("r1", "w1", "Timed out waiting for input after 5 seconds", False, "waiting"),
        ("r2", "w2", "Timed out waiting for input after 60 seconds", False, "waiting"),
    ]


async def test_block_link_resumes_oldest_and_skips_a_lost_race(wire, monkeypatch):
    wire(ScriptedConn({
        "FROM pipeline_wait_links": {"pipeline_id": "p1", "block_id": "wait"},
        "ORDER BY be.started_at": [{"resume_token": "oldest"}, {"resume_token": "next"}],
    }))
    tried = []

    async def fake_resume(token, data):
        tried.append(token)
        if token == "oldest":  # a concurrent call got it first
            return engine.ResumeResult("already_resumed", "r0", "wait", "succeeded")
        return engine.ResumeResult("resumed", "r1", "wait", "succeeded")

    monkeypatch.setattr(engine, "resume_waiting_block", fake_resume)
    result = await engine.resume_by_block_link("link", {"ok": True})
    assert tried == ["oldest", "next"] and result.run_id == "r1"


async def test_block_link_with_nothing_waiting_or_unknown_token(wire):
    wire(ScriptedConn({"FROM pipeline_wait_links": {"pipeline_id": "p1", "block_id": "wait"}}))
    assert (await engine.resume_by_block_link("link", {})).outcome == "nothing_waiting"
    wire(ScriptedConn())
    assert await engine.resume_by_block_link("nope", {}) is None
