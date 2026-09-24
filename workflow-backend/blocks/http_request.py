"""
HTTP Request Block — mirrors n8n's HTTP Request node structure.

Supports:
- Methods: GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS
- Auth: None, Basic Auth, Bearer Token, API Key (header or query param)
- Body types: JSON, Form Data, Raw/Text
- Optional sections: Headers, Query Params, Body (toggled on/off)
- Response shape: { data, headers, statusCode } matching n8n's output

Error classification (block decides, per project design):
- 4xx (except 429): FatalError — bad request, won't succeed on retry
- 429: RetryableError — rate limited, retry with backoff
- 5xx: RetryableError — server error, might succeed on retry
- Network/timeout: RetryableError
"""

import json
from typing import Any

import urllib.request
import urllib.error
import urllib.parse
import base64
import ssl

from blocks.base import BaseBlock, FatalError, RetryableError
from blocks.registry import register_block


# ------------------------------------------------------------------ #
# Schema — what the frontend renders in the config panel              #
# ------------------------------------------------------------------ #

HTTP_BLOCK_SCHEMA = {
    "name": "HTTP Request",
    "category": "Actions",
    "description": "Make HTTP requests to any API or URL",
    "icon": "http",
    "fields": [
        # ── Core ──────────────────────────────────────────────────── #
        {
            "name": "method",
            "label": "Method",
            "type": "options",
            "required": True,
            "default": "GET",
            "options": [
                {"label": "GET",     "value": "GET"},
                {"label": "POST",    "value": "POST"},
                {"label": "PUT",     "value": "PUT"},
                {"label": "PATCH",   "value": "PATCH"},
                {"label": "DELETE",  "value": "DELETE"},
                {"label": "HEAD",    "value": "HEAD"},
                {"label": "OPTIONS", "value": "OPTIONS"},
            ],
        },
        {
            "name": "url",
            "label": "URL",
            "type": "string",
            "required": True,
            "placeholder": "https://api.example.com/endpoint",
            "description": "The URL to make the request to. Supports expressions.",
        },

        # ── Authentication ─────────────────────────────────────────── #
        {
            "name": "authentication",
            "label": "Authentication",
            "type": "options",
            "required": True,
            "default": "none",
            "options": [
                {"label": "None",         "value": "none"},
                {"label": "Basic Auth",   "value": "basic"},
                {"label": "Bearer Token", "value": "bearer"},
                {"label": "API Key",      "value": "apikey"},
            ],
        },
        {
            "name": "basic_username",
            "label": "Username",
            "type": "string",
            "required": True,
            "show_when": {"authentication": "basic"},
        },
        {
            "name": "basic_password",
            "label": "Password",
            "type": "string",
            "required": True,
            "sensitive": True,
            "show_when": {"authentication": "basic"},
        },
        {
            "name": "bearer_token",
            "label": "Bearer Token",
            "type": "string",
            "required": True,
            "sensitive": True,
            "show_when": {"authentication": "bearer"},
        },
        {
            "name": "apikey_value",
            "label": "API Key",
            "type": "string",
            "required": True,
            "sensitive": True,
            "show_when": {"authentication": "apikey"},
        },
        {
            "name": "apikey_location",
            "label": "API Key Location",
            "type": "options",
            "required": True,
            "default": "header",
            "show_when": {"authentication": "apikey"},
            "options": [
                {"label": "Header",      "value": "header"},
                {"label": "Query Param", "value": "query"},
            ],
        },
        {
            "name": "apikey_name",
            "label": "API Key Name",
            "type": "string",
            "required": True,
            "placeholder": "X-API-Key",
            "show_when": {"authentication": "apikey"},
            "description": "The name of the header or query parameter",
        },

        # ── Optional sections (toggled on/off like n8n) ────────────── #
        {
            "name": "send_query_params",
            "label": "Send Query Parameters",
            "type": "boolean",
            "default": False,
        },
        {
            "name": "query_params",
            "label": "Query Parameters",
            "type": "key_value_list",
            "default": [],
            "show_when": {"send_query_params": True},
            "description": "Key-value pairs appended to the URL as query parameters",
        },
        {
            "name": "send_headers",
            "label": "Send Headers",
            "type": "boolean",
            "default": False,
        },
        {
            "name": "headers",
            "label": "Headers",
            "type": "key_value_list",
            "default": [],
            "show_when": {"send_headers": True},
        },
        {
            "name": "send_body",
            "label": "Send Body",
            "type": "boolean",
            "default": False,
            "show_when": {"method": ["POST", "PUT", "PATCH"]},
        },
        {
            "name": "body_content_type",
            "label": "Body Content Type",
            "type": "options",
            "default": "json",
            "show_when": {"send_body": True},
            "options": [
                {"label": "JSON",      "value": "json"},
                {"label": "Form Data", "value": "form"},
                {"label": "Raw/Text",  "value": "raw"},
            ],
        },
        {
            "name": "body_json",
            "label": "Body (JSON)",
            "type": "json",
            "default": {},
            "show_when": {"send_body": True, "body_content_type": "json"},
        },
        {
            "name": "body_form",
            "label": "Body (Form Data)",
            "type": "key_value_list",
            "default": [],
            "show_when": {"send_body": True, "body_content_type": "form"},
        },
        {
            "name": "body_raw",
            "label": "Body (Raw/Text)",
            "type": "string",
            "default": "",
            "show_when": {"send_body": True, "body_content_type": "raw"},
        },

        # ── Options ────────────────────────────────────────────────── #
        {
            "name": "timeout_seconds",
            "label": "Timeout (seconds)",
            "type": "number",
            "default": 30,
            "description": "How long to wait for a response before timing out",
        },
        {
            "name": "ignore_ssl_errors",
            "label": "Ignore SSL Errors",
            "type": "boolean",
            "default": False,
        },
    ],
}


# ------------------------------------------------------------------ #
# Block implementation                                                 #
# ------------------------------------------------------------------ #

# Response body kept in error messages; longer bodies are cut with a marker.
MAX_ERROR_BODY_CHARS = 2000


@register_block("http_request")
class HttpRequestBlock(BaseBlock):
    """
    Generic HTTP Request block.

    Output shape (matches n8n):
    {
        "data": { ...parsed response body (dict if JSON, string otherwise)... },
        "headers": { ...response headers... },
        "statusCode": 200
    }

    Downstream blocks reference: {{http_block.data.customer_id}},
    {{http_block.statusCode}}, etc.
    """

    schema = HTTP_BLOCK_SCHEMA

    # Retry budget: HTTP errors are often transient
    max_retries: int = 3
    retry_backoff_base_seconds: float = 1.0
    retry_backoff_cap_seconds: float = 60.0

    async def execute(
        self,
        config: dict[str, Any],
        input_data: dict[str, Any],
        credentials: dict[str, Any] | None = None
    ) -> dict[str, Any]:

        method  = config.get("method", "GET").upper()
        url     = config.get("url", "").strip()
        timeout = int(config.get("timeout_seconds", 30))

        if not url:
            raise FatalError("HTTP Request block: 'url' is required but was empty.")

        # ── Build headers dict ──────────────────────────────────────── #
        headers: dict[str, str] = {}

        if config.get("send_headers"):
            for pair in config.get("headers", []):
                k = str(pair.get("key", "")).strip()
                v = str(pair.get("value", "")).strip()
                if k:
                    headers[k] = v

        # ── Apply authentication ────────────────────────────────────── #
        auth_type = config.get("authentication", "none")
        query_auth_params: dict[str, str] = {}

        if auth_type == "basic":
            username = config.get("basic_username", "")
            password = config.get("basic_password", "")
            token = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"

        elif auth_type == "bearer":
            token = config.get("bearer_token", "")
            if not token:
                raise FatalError("HTTP Request block: Bearer Token is empty.")
            headers["Authorization"] = f"Bearer {token}"

        elif auth_type == "apikey":
            key_name     = config.get("apikey_name", "").strip()
            key_value    = config.get("apikey_value", "").strip()
            key_location = config.get("apikey_location", "header")
            if not key_name:
                raise FatalError("HTTP Request block: API Key Name is required.")
            if key_location == "header":
                headers[key_name] = key_value
            else:
                query_auth_params[key_name] = key_value

        # ── Build query string ──────────────────────────────────────── #
        query_params: dict[str, str] = {}
        if config.get("send_query_params"):
            for pair in config.get("query_params", []):
                k = str(pair.get("key", "")).strip()
                v = str(pair.get("value", "")).strip()
                if k:
                    query_params[k] = v
        query_params.update(query_auth_params)

        if query_params:
            separator = "&" if "?" in url else "?"
            url = url + separator + urllib.parse.urlencode(query_params)

        # ── Build request body ──────────────────────────────────────── #
        body_bytes: bytes | None = None

        if config.get("send_body") and method not in ("GET", "HEAD", "OPTIONS"):
            content_type = config.get("body_content_type", "json")

            if content_type == "json":
                body_data = config.get("body_json", {})
                if isinstance(body_data, str):
                    # Already JSON text (e.g. one expression that resolved to a
                    # JSON string): decode it so it is encoded only once below.
                    try:
                        body_data = json.loads(body_data)
                    except json.JSONDecodeError as e:
                        raise FatalError(
                            f"HTTP Request block: Body (JSON) is not valid JSON: {e}"
                        )
                body_bytes = json.dumps(body_data).encode("utf-8")
                headers.setdefault("Content-Type", "application/json")

            elif content_type == "form":
                form_pairs = {
                    str(p.get("key", "")): str(p.get("value", ""))
                    for p in config.get("body_form", [])
                    if p.get("key")
                }
                body_bytes = urllib.parse.urlencode(form_pairs).encode("utf-8")
                headers.setdefault(
                    "Content-Type", "application/x-www-form-urlencoded"
                )

            elif content_type == "raw":
                raw = config.get("body_raw", "")
                body_bytes = raw.encode("utf-8")
                headers.setdefault("Content-Type", "text/plain")

        # ── SSL context ─────────────────────────────────────────────── #
        ssl_context = None
        if config.get("ignore_ssl_errors"):
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        # ── Execute request ─────────────────────────────────────────── #
        req = urllib.request.Request(
            url, data=body_bytes, headers=headers, method=method
        )

        try:
            with urllib.request.urlopen(
                req, timeout=timeout, context=ssl_context
            ) as resp:
                raw_body   = resp.read()
                status     = resp.status
                resp_hdrs  = dict(resp.headers)

        except urllib.error.HTTPError as e:
            status    = e.code
            raw_body  = e.read()
            resp_hdrs = dict(e.headers)
            self._raise_for_status(status, raw_body)

        except urllib.error.URLError as e:
            # Network-level failure: DNS, connection refused, timeout
            raise RetryableError(
                f"HTTP Request block: network error — {e.reason}"
            )

        # ── Parse response body ─────────────────────────────────────── #
        content_type_resp = resp_hdrs.get(
            "Content-Type", resp_hdrs.get("content-type", "")
        )

        if "application/json" in content_type_resp:
            try:
                data = json.loads(raw_body.decode("utf-8"))
            except json.JSONDecodeError:
                data = raw_body.decode("utf-8", errors="replace")
        else:
            data = raw_body.decode("utf-8", errors="replace")

        # ── Return n8n-style output ─────────────────────────────────── #
        return {
            "data":       data,
            "headers":    resp_hdrs,
            "statusCode": status,
        }

    @staticmethod
    def _raise_for_status(status: int, body: bytes) -> None:
        body_text = body.decode("utf-8", errors="replace")
        if len(body_text) > MAX_ERROR_BODY_CHARS:
            body_text = body_text[:MAX_ERROR_BODY_CHARS] + "… (truncated)"

        if status == 429:
            raise RetryableError(
                f"HTTP Request block: rate limited (429). Body: {body_text}"
            )
        if 500 <= status < 600:
            raise RetryableError(
                f"HTTP Request block: server error ({status}). Body: {body_text}"
            )
        if 400 <= status < 500:
            raise FatalError(
                f"HTTP Request block: client error ({status}). "
                f"This won't succeed on retry. Body: {body_text}"
            )
