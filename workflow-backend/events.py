import json
import logging
import os

import redis

logger = logging.getLogger(__name__)
_client: redis.Redis | None = None


def publish(run_id: str, event: dict) -> None:
    """Best effort. A publish failure must never affect execution."""
    global _client
    try:
        if _client is None:
            _client = redis.Redis.from_url(
                os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            )
        payload = json.dumps({**event, "run_id": run_id}, default=str)
        _client.publish(f"run:{run_id}", payload)
        _client.publish("runs", payload)
    except Exception:
        logger.exception("event publish failed")
