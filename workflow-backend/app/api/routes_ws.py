import asyncio
import logging
import os

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


async def _forward(websocket: WebSocket, channel: str) -> None:
    """One Redis subscription per connection; each message's data is sent as text."""
    await websocket.accept()
    client = aioredis.Redis.from_url(REDIS_URL)
    pubsub = client.pubsub()

    # Clients never send anything, but reading lets us notice a disconnect
    # while the channel is quiet, so idle subscriptions don't leak.
    async def watch_disconnect() -> None:
        while (await websocket.receive())["type"] != "websocket.disconnect":
            pass

    watcher = asyncio.create_task(watch_disconnect())
    try:
        await pubsub.subscribe(channel)
        while not watcher.done():
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                continue
            data = message["data"]
            await websocket.send_text(data.decode() if isinstance(data, bytes) else str(data))
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("websocket forwarder for %s stopped", channel)
    finally:
        watcher.cancel()
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await client.aclose()
        except Exception:
            logger.exception("websocket cleanup for %s failed", channel)
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/runs")
async def ws_all_runs(websocket: WebSocket) -> None:
    await _forward(websocket, "runs")


@router.websocket("/ws/runs/{run_id}")
async def ws_run(websocket: WebSocket, run_id: str) -> None:
    await _forward(websocket, f"run:{run_id}")
