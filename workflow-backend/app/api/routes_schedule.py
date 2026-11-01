from datetime import datetime, timezone

from fastapi import APIRouter

from app.api.models import SchedulePreviewRequest, SchedulePreviewResponse
from blocks.schedule_trigger import next_occurrences

router = APIRouter()


@router.post("/preview", response_model=SchedulePreviewResponse)
async def preview_schedule(body: SchedulePreviewRequest) -> SchedulePreviewResponse:
    """The next 5 fire times, so the UI never re-implements cron semantics.
    An invalid cron or timezone is a 400 (ValueError handler in app.main)."""
    times = next_occurrences(body.cron, body.timezone, datetime.now(timezone.utc), 5)
    return SchedulePreviewResponse(times=times)
