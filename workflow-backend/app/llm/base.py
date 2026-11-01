"""
Provider-neutral types for the LLM block.

A provider turns one LLMRequest into one LLMResponse, or raises one of the
LLMProviderError subclasses below. Providers never decide whether a failure
is worth retrying: they report what happened, and the block maps that onto
RetryableError / FatalError (the block contract in blocks/base.py).
"""

import http.client
import json
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

# Response body kept in error messages; same limit as the HTTP Request block.
MAX_ERROR_BODY_CHARS = 2000


@dataclass
class LLMRequest:
    model: str
    prompt: str
    api_key: str
    system_prompt: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    json_mode: bool = False
    json_schema: dict | None = None
    timeout_seconds: float = 60


@dataclass
class LLMUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class LLMResponse:
    text: str
    # Normalized, lowercase: "stop", "max_tokens", or the provider's own
    # reason lowercased for anything else.
    finish_reason: str | None
    usage: LLMUsage = field(default_factory=LLMUsage)
    model: str | None = None


class LLMProviderError(Exception):
    """Base for every failure a provider reports. Messages never contain the key."""


class ProviderHTTPError(LLMProviderError):
    def __init__(
        self,
        status: int,
        body: str,
        retry_after_seconds: float | None = None,
        reason: str | None = None,
    ):
        self.status = status
        self.body = body
        self.retry_after_seconds = retry_after_seconds
        # Normalized cause when the provider says, e.g. "invalid_api_key".
        self.reason = reason
        super().__init__(f"HTTP {status}: {body}")


class ProviderTimeout(LLMProviderError):
    pass


class ProviderConnectionError(LLMProviderError):
    pass


class ContentBlocked(LLMProviderError):
    """The provider refused the prompt or stopped the answer for safety/policy."""


class EmptyResponse(LLMProviderError):
    """The provider answered 200 but with no candidate to read."""


class MalformedResponse(LLMProviderError):
    """The provider answered 200 with a body we can't interpret."""


class LLMProvider(Protocol):
    # Environment variable the block falls back to when no api_key is configured.
    env_var: str
    default_model: str
    # Choices for the block's model dropdown: {"label", "value"}.
    models: list[dict[str, str]]
    # Credential type (app/credentials.py) whose secrets this provider accepts.
    credential_type: str
    credential_label: str

    def generate(self, request: LLMRequest) -> LLMResponse: ...


# ------------------------------------------------------------------ #
# Transport: the one place that touches the network, so tests swap it #
# ------------------------------------------------------------------ #

@dataclass
class TransportResponse:
    status: int
    headers: dict[str, str]
    body: bytes


Transport = Callable[[str, dict[str, str], bytes, float], TransportResponse]


def urllib_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> TransportResponse:
    """POSTs with urllib, the same client the HTTP Request block uses.
    Non-2xx statuses are returned, not raised; network failures raise
    ProviderTimeout / ProviderConnectionError."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return TransportResponse(resp.status, dict(resp.headers), resp.read())
    except urllib.error.HTTPError as e:
        return TransportResponse(e.code, dict(e.headers or {}), e.read())
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise ProviderTimeout(f"timed out after {timeout:g}s") from None
        raise ProviderConnectionError(f"network error: {e.reason}") from None
    except TimeoutError:
        raise ProviderTimeout(f"timed out after {timeout:g}s") from None
    except (http.client.HTTPException, ssl.SSLError, OSError) as e:
        raise ProviderConnectionError(f"network error: {type(e).__name__}: {e}") from None


def truncate_body(text: str, secret: str | None = None) -> str:
    """Error-message form of a response body: secret scrubbed, then cut."""
    if secret:
        text = text.replace(secret, "[redacted]")
    if len(text) > MAX_ERROR_BODY_CHARS:
        text = text[:MAX_ERROR_BODY_CHARS] + "… (truncated)"
    return text


def parse_retry_after(value: str | None) -> float | None:
    """Retry-After in delta-seconds form. The HTTP-date form is ignored."""
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def loads_or_none(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
