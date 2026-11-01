"""
Schedule Trigger — starts the pipeline on a 5-field cron schedule.

The engine never runs cron itself: engine/triggers.py keeps
pipeline_triggers.next_run_at up to date and the beat task
fire_due_schedules starts a run whenever it falls due. The run's
trigger_payload ({scheduled_for, fired_at}) becomes this block's output.
"""

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from blocks.base import BaseBlock
from blocks.registry import register_block

DEFAULT_TIMEZONE = "UTC"


def _zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"Unknown timezone '{tz_name}'.") from e


def schedule_problem(cron: Any, tz_name: Any) -> str | None:
    """Why (cron, timezone) can't be scheduled, or None if it can."""
    if not isinstance(cron, str) or not cron.strip():
        return "a cron expression is required."
    if len(cron.split()) != 5:
        return f"cron '{cron}' must have exactly 5 fields (minute hour day month weekday)."
    if not croniter.is_valid(cron):
        return f"cron '{cron}' is not a valid cron expression."
    try:
        _zone(tz_name or DEFAULT_TIMEZONE)
    except ValueError as e:
        return str(e)
    return None


def next_occurrences(cron: str, tz_name: str | None, after: datetime, count: int) -> list[datetime]:
    """The next `count` fire times strictly after `after`, as UTC datetimes.
    Cron fields are read as wall-clock time in tz_name, so "0 9 * * *" in
    Europe/London stays at 09:00 local across DST changes."""
    problem = schedule_problem(cron, tz_name)
    if problem:
        raise ValueError(problem)
    zone = _zone(tz_name or DEFAULT_TIMEZONE)
    # When clocks go back, an hour of wall-clock time happens twice. Like
    # Vixie cron, a job pinned to specific hours fires once (the first
    # pass); a wildcard-hour job keeps firing on real elapsed time.
    skip_repeats = cron.split()[1] != "*"
    it = croniter(cron, after.astimezone(zone))
    out: list[datetime] = []
    while len(out) < count:
        local = it.get_next(datetime)
        if skip_repeats and _is_second_pass(local, zone):
            continue
        out.append(local.astimezone(timezone.utc))
    return out


def _is_second_pass(local: datetime, zone: ZoneInfo) -> bool:
    """True for the later of two instants sharing an ambiguous wall time."""
    naive = local.replace(tzinfo=None)
    first = naive.replace(tzinfo=zone, fold=0).astimezone(timezone.utc)
    second = naive.replace(tzinfo=zone, fold=1).astimezone(timezone.utc)
    return first != second and local.astimezone(timezone.utc) == second


def next_occurrence(cron: str, tz_name: str | None, after: datetime) -> datetime:
    """The first fire time strictly after `after`. The scheduler always
    passes NOW, never the missed slot, so downtime never causes a burst."""
    return next_occurrences(cron, tz_name, after, 1)[0]


@register_block("schedule_trigger")
class ScheduleTriggerBlock(BaseBlock):
    schema = {
        "name": "Schedule Trigger",
        "category": "Triggers",
        "description": "Starts the workflow on a cron schedule while it is active.",
        "fields": [
            {"name": "cron", "label": "Cron expression", "type": "string", "required": True,
             "default": "0 9 * * *", "placeholder": "*/15 * * * *",
             "description": "5 fields: minute hour day-of-month month day-of-week."},
            {"name": "timezone", "label": "Timezone", "type": "string", "default": DEFAULT_TIMEZONE,
             "description": "IANA name, e.g. Europe/London."},
        ],
    }

    async def execute(
        self,
        config: dict[str, Any],
        input_data: dict[str, Any],
        credentials: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        # input_data is the run's trigger_payload: {scheduled_for, fired_at}.
        return dict(input_data or {})
