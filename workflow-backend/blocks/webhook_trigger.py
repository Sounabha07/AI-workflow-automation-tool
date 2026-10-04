"""
Webhook Trigger — starts the pipeline when POST /hooks/{token} is called.

The route (app/api/routes_hooks.py) verifies the optional HMAC signature,
builds the payload with build_payload() and stores it as the run's
trigger_payload, which becomes this block's output.
"""

import hashlib
import hmac
import json
from typing import Any

from blocks.base import BaseBlock
from blocks.registry import register_block

DEFAULT_SIGNATURE_HEADER = "X-Hub-Signature-256"
# Never copied into the payload: credentials, and the signature itself.
_DROPPED_HEADERS = {"authorization", "cookie"}


def expected_signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, header_value: str | None) -> bool:
    """GitHub-style `sha256=<hex hmac of the raw body>`, constant-time compare."""
    if not header_value:
        return False
    return hmac.compare_digest(
        expected_signature(secret, body).encode(), header_value.strip().encode()
    )


def parse_body(raw: bytes) -> Any:
    """JSON when it parses, None when empty, otherwise the raw text."""
    if not raw.strip():
        return None
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def build_payload(
    method: str,
    raw_body: bytes,
    query: dict[str, str],
    headers: dict[str, str],
    signature_header: str = DEFAULT_SIGNATURE_HEADER,
) -> dict[str, Any]:
    dropped = _DROPPED_HEADERS | {signature_header.lower()}
    return {
        "method": method.upper(),
        "body": parse_body(raw_body),
        "query": dict(query),
        "headers": {k.lower(): v for k, v in headers.items() if k.lower() not in dropped},
    }


@register_block("webhook_trigger")
class WebhookTriggerBlock(BaseBlock):
    schema = {
        "name": "Webhook Trigger",
        "category": "Triggers",
        "description": "Starts the workflow when its URL receives a POST while the workflow is active.",
        "fields": [
            {"name": "secret", "label": "Signing secret", "type": "string", "sensitive": True,
             "description": "Optional. When set, requests must carry sha256=<HMAC of the body> "
                            "in the signature header (GitHub style)."},
            {"name": "signature_header", "label": "Signature header", "type": "string",
             "default": DEFAULT_SIGNATURE_HEADER},
        ],
    }

    async def execute(
        self,
        config: dict[str, Any],
        input_data: dict[str, Any],
        credentials: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        # input_data is the run's trigger_payload: {method, body, query, headers}.
        return dict(input_data or {})
