from datetime import datetime, timedelta, timezone

import pytest

import engine
import engine.triggers as triggers
from blocks.schedule_trigger import next_occurrence, next_occurrences, schedule_problem
from tests.fakes import ScriptedConn

UTC = timezone.utc


def utc(*args):
    return datetime(*args, tzinfo=UTC)


def test_next_occurrence_is_strictly_after():
    assert next_occurrence("*/15 * * * *", "UTC", utc(2026, 1, 1, 10, 0)) == utc(2026, 1, 1, 10, 15)
    assert next_occurrence("*/15 * * * *", "UTC", utc(2026, 1, 1, 10, 7)) == utc(2026, 1, 1, 10, 15)


def test_timezone_cron_keeps_local_wall_clock_across_dst_start():
    # US DST starts 2026-03-08: 09:00 New York is 14:00 UTC before, 13:00 after.
    times = next_occurrences("0 9 * * *", "America/New_York", utc(2026, 3, 6, 20, 0), 3)
    assert times == [utc(2026, 3, 7, 14, 0), utc(2026, 3, 8, 13, 0), utc(2026, 3, 9, 13, 0)]


def test_fixed_time_in_repeated_hour_fires_once_when_clocks_go_back():
    # 2026-11-01 01:30 happens twice in New York; a daily job runs once.
    times = next_occurrences("30 1 * * *", "America/New_York", utc(2026, 10, 31, 0, 0), 3)
    assert times == [utc(2026, 10, 31, 5, 30), utc(2026, 11, 1, 5, 30), utc(2026, 11, 2, 6, 30)]


def test_wildcard_hour_keeps_firing_through_the_repeated_hour():
    times = next_occurrences("30 * * * *", "America/New_York", utc(2026, 11, 1, 4, 0), 3)
    assert times == [utc(2026, 11, 1, 4, 30), utc(2026, 11, 1, 5, 30), utc(2026, 11, 1, 6, 30)]


def test_skip_missed_rule_next_is_after_now_not_after_the_missed_slot():
    # Beat was down: the stored slot is an hour old. The next slot is
    # computed from now, so a minutely cron doesn't owe 60 catch-up runs.
    now = utc(2026, 5, 1, 12, 0, 30)
    assert next_occurrence("* * * * *", "UTC", now) == utc(2026, 5, 1, 12, 1)


@pytest.mark.parametrize("cron,tz,fragment", [
    ("", "UTC", "required"),
    ("* * * *", "UTC", "exactly 5 fields"),
    ("0 0 * * * *", "UTC", "exactly 5 fields"),
    ("61 * * * *", "UTC", "not a valid cron"),
    ("* * * * *", "Mars/Base", "Unknown timezone"),
    ("* * * * *", "../etc/passwd", "Unknown timezone"),
])
def test_schedule_problem_rejects(cron, tz, fragment):
    assert fragment in schedule_problem(cron, tz)


def test_schedule_problem_accepts_valid():
    assert schedule_problem("0 9 * * 1-5", "Europe/London") is None


async def test_fire_due_schedules_fires_once_and_advances_past_now(monkeypatch):
    missed_slot = datetime.now(UTC) - timedelta(minutes=10)
    due = [{"id": "trig-1", "pipeline_id": "pipe-1", "cron_expr": "* * * * *",
            "timezone": "UTC", "next_run_at": missed_slot}]
    conn = ScriptedConn({"FOR UPDATE OF t SKIP LOCKED": due})
    created, dispatched = [], []

    async def fake_create_run(c, pipeline_id, **kw):
        created.append((pipeline_id, kw))
        return engine.CreatedRun("run-1", pipeline_id, ["sched"], True)

    async def fake_get_connection():
        return conn

    monkeypatch.setattr(triggers, "get_connection", fake_get_connection)
    monkeypatch.setattr(engine, "create_run", fake_create_run)
    monkeypatch.setattr(engine, "dispatch_run", dispatched.append)

    before = datetime.now(UTC)
    assert await triggers.fire_due_schedules() == ["run-1"]

    assert len(created) == 1  # one run, not one per missed minute
    pipeline_id, kw = created[0]
    assert pipeline_id == "pipe-1" and kw["trigger_type"] == "schedule" and kw["trigger_id"] == "trig-1"
    assert kw["trigger_payload"]["scheduled_for"] == missed_slot.isoformat()
    assert [r.run_id for r in dispatched] == ["run-1"]

    (_, (trigger_id, next_run_at, _fired)), = [
        c for c in conn.calls if "UPDATE pipeline_triggers SET next_run_at" in c[0]
    ]
    assert trigger_id == "trig-1"
    assert next_run_at > before  # landed in the future
    assert next_run_at - before <= timedelta(minutes=1)


async def test_fire_due_schedules_with_nothing_due(monkeypatch):
    conn = ScriptedConn()

    async def fake_get_connection():
        return conn

    monkeypatch.setattr(triggers, "get_connection", fake_get_connection)
    assert await triggers.fire_due_schedules() == []
    assert not conn.ran("UPDATE pipeline_triggers")


async def test_activation_recomputes_from_now_only_when_switched_on():
    conn = ScriptedConn({
        "SELECT is_active FROM pipelines": False,
        "FROM pipeline_triggers": [{"id": "t1", "cron_expr": "*/5 * * * *", "timezone": "UTC"}],
    })
    before = datetime.now(UTC)
    assert await triggers.set_pipeline_active(conn, "p1", True) is False
    (_, (tid, next_run_at)), = [c for c in conn.calls if "SET next_run_at" in c[0]]
    assert tid == "t1" and before < next_run_at <= before + timedelta(minutes=5)

    already_on = ScriptedConn({"SELECT is_active FROM pipelines": True})
    await triggers.set_pipeline_active(already_on, "p1", True)
    assert not already_on.ran("SET next_run_at")
