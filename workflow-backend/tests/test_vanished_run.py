"""A run deleted mid-flight (its pipeline was deleted, cascading) must make
in-flight block tasks stop quietly instead of raising."""

import pytest

import engine
import tasks
from tests.fakes import ScriptedConn


@pytest.fixture
def fake_conn(monkeypatch):
    def install(conn):
        async def fake_get_connection():
            return conn

        monkeypatch.setattr(engine, "get_connection", fake_get_connection)
        return conn

    return install


async def test_get_block_context_raises_run_vanished(fake_conn):
    fake_conn(ScriptedConn())  # the block_execution row is gone
    with pytest.raises(engine.RunVanishedError):
        await engine.get_block_context("r1", "b1")


async def test_success_after_the_run_vanished_writes_nothing_more(fake_conn, monkeypatch):
    conn = fake_conn(ScriptedConn())  # UPDATE ... RETURNING retry_count finds no row
    published, dispatched = [], []
    monkeypatch.setattr(engine.events, "publish", lambda run_id, e: published.append(e))
    monkeypatch.setattr(engine, "_dispatch", lambda run_id, ids: dispatched.extend(ids))

    await engine.handle_block_success("r1", "b1", {"x": 1})

    assert not conn.ran("pipeline_snapshot") and not conn.ran("blocks_remaining")
    assert published == [] and dispatched == []


@pytest.fixture
def task_engine(monkeypatch):
    """Stubs the engine calls execute_block_task makes; records failures."""
    failures = []

    async def not_failed(run_id):
        return False

    async def record_failure(run_id, block_id, message, retryable, attempts, from_status=None):
        failures.append(message)
        return True

    monkeypatch.setattr(engine, "is_run_failed", not_failed)
    monkeypatch.setattr(engine, "handle_block_failure", record_failure)
    return failures


def test_task_returns_quietly_when_the_run_vanished(monkeypatch, task_engine):
    async def vanished(run_id, block_id):
        raise engine.RunVanishedError("gone")

    monkeypatch.setattr(engine, "get_block_context", vanished)
    assert tasks.execute_block_task("r1", "b1") is None
    assert task_engine == []  # not treated as a block failure


def test_task_still_fails_the_block_on_an_unresolvable_reference(monkeypatch, task_engine):
    async def bad_ref(run_id, block_id):
        raise ValueError("Reference '{{ missing.x }}' has no output")

    monkeypatch.setattr(engine, "get_block_context", bad_ref)
    tasks.execute_block_task("r1", "b1")
    assert task_engine == ["Reference '{{ missing.x }}' has no output"]
