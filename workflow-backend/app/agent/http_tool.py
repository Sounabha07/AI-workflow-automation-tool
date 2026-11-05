"""
One tool call on an http_request block.

The model's arguments are passed straight through (never templated):
merged with the static fields, `{name}` path params filled in, then sent as
query params (GET, DELETE, HEAD, OPTIONS) or the JSON body (POST, PUT,
PATCH) through the HTTP block's own execute path, so headers, auth and error
classification are the block's. The model never controls the method, host,
headers or auth: the final URL must keep the configured scheme, host and port.
"""

import asyncio
import base64
import json
import math
import re
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.tools import side_effects, static_fields
from blocks.base import EngineError, RetryableError

MASK = "••••••••"
BODY_METHODS = ("POST", "PUT", "PATCH")
BODY_SNIPPET_CHARS = 500
# {name}, but not {{ expression }}.
PATH_PARAM = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})")

# Takes the HTTP block config to run, returns the block's output.
Executor = Callable[[dict], Awaitable[dict]]


class ToolArgumentError(Exception):
    """The call can't be built from these arguments. Goes back to the model."""


@dataclass
class ToolResult:
    ok: bool
    # What the model sees: always a JSON object.
    response: dict
    # Stored in the trace: the request (secrets masked) and the full result.
    request: dict | None = None
    full_result: Any = None
    error: str | None = None
    status: int | None = None
    retryable: bool = False
    side_effects: bool = True
    attempts: int = 0
    extra: dict = field(default_factory=dict)


# ── secrets ─────────────────────────────────────────────────────────── #

def secrets_of(config: dict) -> list[str]:
    """Every secret value this block's auth puts on the wire."""
    out: list[str] = []
    auth = config.get("authentication", "none")
    if auth == "basic":
        user, pw = str(config.get("basic_username", "")), str(config.get("basic_password", ""))
        out += [pw, base64.b64encode(f"{user}:{pw}".encode()).decode()]
    elif auth == "bearer":
        out.append(str(config.get("bearer_token", "")))
    elif auth == "apikey":
        value = str(config.get("apikey_value", "")).strip()
        out += [value, urllib.parse.quote_plus(value), urllib.parse.quote(value, safe="")]
    return sorted({s for s in out if len(s) >= 4}, key=len, reverse=True)


def scrub(value: Any, secrets: list[str]) -> Any:
    """`value` with every secret replaced by MASK, structurally."""
    if not secrets:
        return value
    if isinstance(value, str):
        for s in secrets:
            value = value.replace(s, MASK)
        return value
    if isinstance(value, dict):
        return {scrub(k, secrets): scrub(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, secrets) for v in value]
    return value


# ── request building ────────────────────────────────────────────────── #

def _origin(url: str) -> tuple:
    parts = urllib.parse.urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = "invalid"
    return parts.scheme.lower(), (parts.hostname or "").lower(), port


def _path_value(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    encoded = urllib.parse.quote(text, safe="")
    # "." and ".." are left alone by quote() but are path navigation.
    if encoded in (".", ".."):
        encoded = encoded.replace(".", "%2E")
    return encoded


def _query_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, separators=(",", ":"))


def build_request(config: dict, args: dict) -> tuple[dict, dict]:
    """(HTTP block config to execute, request summary with secrets masked).
    Raises ToolArgumentError for a call the model has to fix."""
    if not isinstance(args, dict):
        raise ToolArgumentError("arguments must be a JSON object")
    fixed = static_fields(config)
    if not isinstance(fixed, dict):
        raise ToolArgumentError("the tool's static fields are not an object")
    payload = {**args, **fixed}

    method = str(config.get("method") or "GET").upper()
    configured_url = str(config.get("url") or "").strip()
    if not configured_url:
        raise ToolArgumentError("the tool has no URL configured")

    missing: list[str] = []

    def fill(m: re.Match) -> str:
        name = m.group(1)
        if payload.get(name) in (None, ""):
            missing.append(name)
            return m.group(0)
        return _path_value(payload.pop(name))

    url = PATH_PARAM.sub(fill, configured_url)
    if missing:
        raise ToolArgumentError(f"missing required path parameter(s): {', '.join(missing)}")

    # Compare against the configured URL with its placeholders blanked, so a
    # placeholder can't sit in the host part and pass.
    if _origin(url) != _origin(PATH_PARAM.sub("", configured_url)) or not _origin(url)[1]:
        raise ToolArgumentError("the arguments would change the URL's scheme, host or port; that's not allowed")

    exec_config = {**config, "url": url}
    if method in BODY_METHODS:
        exec_config.update(send_body=True, body_content_type="json", body_json=payload)
        query_pairs: list[dict] = []
    else:
        exec_config["send_body"] = False
        query_pairs = [{"key": k, "value": _query_value(v)} for k, v in payload.items() if v is not None]
        if query_pairs:
            existing = list(config.get("query_params") or []) if config.get("send_query_params") else []
            exec_config.update(send_query_params=True, query_params=existing + query_pairs)

    summary = request_summary(exec_config, method, payload if method in BODY_METHODS else None)
    return exec_config, summary


def request_summary(exec_config: dict, method: str, body: Any) -> dict:
    """The request as the trace shows it: auth headers and keys masked."""
    headers = {}
    if exec_config.get("send_headers"):
        for pair in exec_config.get("headers") or []:
            k = str(pair.get("key", "")).strip()
            if k:
                headers[k] = str(pair.get("value", ""))
    query = {}
    if exec_config.get("send_query_params"):
        query = {str(p.get("key")): str(p.get("value", "")) for p in exec_config.get("query_params") or [] if p.get("key")}
    auth = exec_config.get("authentication", "none")
    if auth in ("basic", "bearer"):
        headers["Authorization"] = MASK
    elif auth == "apikey":
        target = headers if exec_config.get("apikey_location", "header") == "header" else query
        target[str(exec_config.get("apikey_name", "")).strip() or "api_key"] = MASK
    for k in list(headers):
        if k.lower() in ("authorization", "proxy-authorization", "cookie", "x-api-key"):
            headers[k] = MASK
    summary = {"method": method, "url": exec_config["url"], "query": query, "headers": headers}
    if body is not None:
        summary["body"] = body
    return scrub(summary, secrets_of(exec_config))


# ── execution ───────────────────────────────────────────────────────── #

async def default_executor(exec_config: dict) -> dict:
    """The HTTP block's normal execute path, in a thread: urllib blocks, and
    parallel tool calls must not wait on each other."""
    from blocks.http_request import HttpRequestBlock

    return await asyncio.to_thread(asyncio.run, HttpRequestBlock().execute(exec_config, {}))


def _lookup(data: Any, path: str) -> Any:
    current = data
    for seg in [s for s in path.strip().split(".") if s]:
        if isinstance(current, dict) and seg in current:
            current = current[seg]
        elif isinstance(current, list) and seg.lstrip("-").isdigit() and -len(current) <= int(seg) < len(current):
            current = current[int(seg)]
        else:
            return None
    return current


def map_output(data: Any, mapping: Any) -> Any:
    pairs = [p for p in mapping or [] if isinstance(p, dict) and str(p.get("key", "")).strip()]
    if not pairs:
        return data
    return {str(p["key"]).strip(): _lookup(data, str(p.get("value", ""))) for p in pairs}


def truncate_for_model(value: Any, limit: int) -> dict:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return {"result": value}
    return {
        "result": text[:limit] + f" …[truncated: showing {limit} of {len(text)} characters]",
        "truncated": True,
    }


def _error_response(e: EngineError, retryable: bool, secrets: list[str]) -> dict:
    body = e.body if e.body is not None else ""
    return scrub({
        "error": str(e),
        "status": e.status,
        "body_snippet": body[:BODY_SNIPPET_CHARS],
        "retryable": retryable,
    }, secrets)


async def call_tool(
    config: dict,
    args: dict,
    *,
    timeout_seconds: float,
    max_result_chars: int,
    executor: Executor | None = None,
    inline_retries: int = 2,
    backoff_seconds: float = 0.5,
) -> ToolResult:
    """Runs one validated call. Never raises for an HTTP or argument
    problem: the result describes it for the model. Only side-effect free
    calls are retried here, and only when the HTTP block calls the error
    retryable."""
    executor = executor or default_executor
    secrets = secrets_of(config)
    effects = side_effects(config)
    try:
        exec_config, summary = build_request(config, args)
    except ToolArgumentError as e:
        return ToolResult(False, {"error": f"invalid call: {e}"}, error=str(e), side_effects=effects)

    exec_config["timeout_seconds"] = max(1, math.ceil(timeout_seconds))
    attempts_allowed = 1 + (inline_retries if not effects else 0)
    last: ToolResult | None = None
    for attempt in range(1, attempts_allowed + 1):
        try:
            output = await asyncio.wait_for(executor(exec_config), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            e = RetryableError(f"the tool call timed out after {timeout_seconds:g}s")
            last = ToolResult(False, _error_response(e, True, secrets), request=summary, error=str(e),
                              retryable=True, side_effects=effects, attempts=attempt)
        except EngineError as e:
            retryable = isinstance(e, RetryableError)
            last = ToolResult(False, _error_response(e, retryable, secrets), request=summary,
                              error=scrub(str(e), secrets), status=e.status, retryable=retryable,
                              side_effects=effects, attempts=attempt)
        else:
            output = scrub(output, secrets)
            mapped = map_output(output.get("data"), config.get("output_mapping"))
            return ToolResult(
                True,
                truncate_for_model(mapped, max_result_chars),
                request=summary,
                full_result={"statusCode": output.get("statusCode"), "data": output.get("data"),
                             **({"mapped": mapped} if mapped is not output.get("data") else {})},
                status=output.get("statusCode"),
                side_effects=effects,
                attempts=attempt,
            )
        if not last.retryable or attempt == attempts_allowed:
            break
        await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))
    return last
