"""
Test-only endpoints, mounted only when ENABLE_TEST_PROVIDERS=1 (CI and the
smoke test). They exist so agent tool calls and crash drills can be checked
without any third-party service.

    GET|POST|PUT|PATCH|DELETE /_test/echo[/anything]?delay_ms=
        Counts the request against its path, then (after delay_ms) returns it.
    GET /_test/echo/count[?path=/_test/echo/x]
        The counter for one path, or all of them.

Counters live in Redis so they survive API reloads and are shared by every
API process. The count goes up before the delay, so a caller killed
mid-request still counts.
"""

import asyncio
import json
import os

import redis.asyncio as aioredis
from fastapi import APIRouter, Request

from app.api.body import read_limited_body

router = APIRouter()

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
COUNTER_KEY = "test_echo:counts"
MAX_DELAY_MS = 120_000

_client: aioredis.Redis | None = None


def _redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.Redis.from_url(REDIS_URL)
    return _client


@router.get("/echo/count")
async def echo_count(path: str | None = None) -> dict:
    counts = {k.decode(): int(v) for k, v in (await _redis().hgetall(COUNTER_KEY)).items()}
    if path is not None:
        return {"path": path, "count": counts.get(path, 0)}
    return {"counts": counts}


@router.api_route("/echo", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
@router.api_route("/echo/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
async def echo(request: Request, delay_ms: int = 0, rest: str = "") -> dict:
    path = request.url.path
    count = await _redis().hincrby(COUNTER_KEY, path, 1)
    raw = await read_limited_body(request)
    try:
        body = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        body = raw.decode(errors="replace")
    if delay_ms > 0:
        await asyncio.sleep(min(delay_ms, MAX_DELAY_MS) / 1000)
    return {
        "method": request.method,
        "path": path,
        "query": {k: v for k, v in request.query_params.items() if k != "delay_ms"},
        "body": body,
        "headers": dict(request.headers),
        "count": count,
    }
