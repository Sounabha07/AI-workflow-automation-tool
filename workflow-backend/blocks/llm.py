"""
LLM Block — one prompt in, one response out. A pure transform: no tools,
no agent loop. Provider-specific details live in app/llm/.

Output:
    {"text", "json", "finish_reason", "usage": {input_tokens, output_tokens,
     total_tokens}, "model"}
Downstream blocks reference {{ llm_1.text }} or {{ llm_1.json.some_field }}.

Error classification (block decides, per project design):
- 429, 5xx, timeouts, connection errors: RetryableError (Retry-After honored)
- json mode and the answer isn't valid JSON: RetryableError
- other 4xx, missing key, blocked prompt/answer, no candidates: FatalError
- finishReason MAX_TOKENS is a success, surfaced in finish_reason
"""

import asyncio
import json
import os
from typing import Any

from app.llm import DEFAULT_PROVIDER, PROVIDER_LABELS, PROVIDERS
from app.llm.base import (
    ContentBlocked,
    EmptyResponse,
    LLMProviderError,
    LLMRequest,
    MalformedResponse,
    ProviderConnectionError,
    ProviderHTTPError,
    ProviderTimeout,
)
from blocks.base import BaseBlock, FatalError, RetryableError
from blocks.registry import register_block

RESPONSE_FORMATS = ("text", "json")
_DEFAULT_MODEL = PROVIDERS[DEFAULT_PROVIDER].default_model
_DEFAULT_ENV_VAR = PROVIDERS[DEFAULT_PROVIDER].env_var
TEMPERATURE_RANGE = (0.0, 2.0)

LLM_BLOCK_SCHEMA = {
    "name": "LLM",
    "category": "llm",
    "description": "Send one prompt to a language model and get its answer",
    "icon": "llm",
    "fields": [
        {
            "name": "provider",
            "label": "Provider",
            "type": "options",
            "required": True,
            "default": DEFAULT_PROVIDER,
            "options": [{"label": PROVIDER_LABELS.get(k, k), "value": k} for k in PROVIDERS],
        },
        {
            "name": "model",
            "label": "Model",
            "type": "string",
            "required": True,
            "default": _DEFAULT_MODEL,
            "placeholder": _DEFAULT_MODEL,
            "description": "Any model name the provider accepts.",
        },
        {
            "name": "prompt",
            "label": "Prompt",
            "type": "text",
            "required": True,
            "placeholder": "Summarize this: {{ input_1.text }}",
            "description": "Drag fields in from the input pane. Objects are inserted as JSON.",
        },
        {
            "name": "system_prompt",
            "label": "System prompt",
            "type": "text",
            "placeholder": "You are a concise assistant.",
        },
        {
            "name": "temperature",
            "label": "Temperature",
            "type": "number",
            "default": 1.0,
            "description": "0 to 2. Lower is more predictable.",
        },
        {
            "name": "max_output_tokens",
            "label": "Max output tokens",
            "type": "number",
            "placeholder": "Model default",
        },
        {
            "name": "response_format",
            "label": "Response format",
            "type": "options",
            "required": True,
            "default": "text",
            "options": [
                {"label": "Text", "value": "text"},
                {"label": "JSON", "value": "json"},
            ],
        },
        {
            "name": "json_schema",
            "label": "JSON schema",
            "type": "json",
            "placeholder": '{"type": "object", "properties": {"summary": {"type": "string"}}}',
            "show_when": {"response_format": "json"},
            "description": "Optional. The answer is constrained to this schema.",
        },
        {
            "name": "timeout_seconds",
            "label": "Timeout (seconds)",
            "type": "number",
            "default": 60,
            "description": "Per attempt.",
        },
        {
            "name": "credential",
            "label": "Credential",
            "type": "credential",
            "credential_types": [p.credential_type for p in PROVIDERS.values()],
            "placeholder": f"None: use the server's {_DEFAULT_ENV_VAR}",
            "description": "Your own saved API key. With none selected, the server's key is used if one is set.",
        },
    ],
}


def _number(value: Any, name: str, *, integer: bool = False) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise FatalError(f"LLM block: '{name}' must be a number, got {value!r}.")
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise FatalError(f"LLM block: '{name}' must be a number, got {value!r}.") from None
    if integer:
        if n != int(n) or n < 1:
            raise FatalError(f"LLM block: '{name}' must be a positive whole number, got {value!r}.")
        return int(n)
    return n


@register_block("llm")
class LLMBlock(BaseBlock):
    schema = LLM_BLOCK_SCHEMA

    max_retries: int = 3
    retry_backoff_base_seconds: float = 2.0
    retry_backoff_cap_seconds: float = 60.0

    def __init__(self, providers: dict | None = None):
        # Tests pass provider instances with a fake transport.
        self._providers = providers

    def _provider(self, name: str):
        if self._providers is not None and name in self._providers:
            return self._providers[name]
        if name not in PROVIDERS:
            raise FatalError(
                f"LLM block: unknown provider '{name}'. Available: {', '.join(PROVIDERS)}."
            )
        return PROVIDERS[name]()

    async def execute(
        self,
        config: dict[str, Any],
        input_data: dict[str, Any],
        credentials: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        provider_name = str(config.get("provider") or DEFAULT_PROVIDER)
        provider = self._provider(provider_name)

        prompt = config.get("prompt")
        if not isinstance(prompt, str):
            prompt = "" if prompt is None else json.dumps(prompt, ensure_ascii=False, default=str)
        if not prompt.strip():
            raise FatalError("LLM block: 'prompt' is required but was empty.")

        system_prompt = config.get("system_prompt")
        if system_prompt is not None and not isinstance(system_prompt, str):
            system_prompt = json.dumps(system_prompt, ensure_ascii=False, default=str)

        model = str(config.get("model") or "").strip() or provider.default_model

        temperature = _number(config.get("temperature", 1.0), "temperature")
        if temperature is not None and not TEMPERATURE_RANGE[0] <= temperature <= TEMPERATURE_RANGE[1]:
            raise FatalError(f"LLM block: 'temperature' must be between 0 and 2, got {temperature:g}.")
        max_tokens = _number(config.get("max_output_tokens"), "max_output_tokens", integer=True)
        timeout = _number(config.get("timeout_seconds", 60), "timeout_seconds") or 60

        response_format = config.get("response_format") or "text"
        if response_format not in RESPONSE_FORMATS:
            raise FatalError(f"LLM block: 'response_format' must be 'text' or 'json', got {response_format!r}.")
        json_mode = response_format == "json"
        json_schema = config.get("json_schema") or None
        if isinstance(json_schema, str):
            try:
                json_schema = json.loads(json_schema)
            except json.JSONDecodeError as e:
                raise FatalError(f"LLM block: 'json_schema' is not valid JSON: {e}") from None
        if json_schema is not None and not isinstance(json_schema, dict):
            raise FatalError("LLM block: 'json_schema' must be a JSON object.")

        # A saved credential (decrypted by the engine, never in config) wins;
        # the server's environment variable is the operator fallback.
        if credentials:
            if credentials.get("type") != provider.credential_type:
                raise FatalError(
                    f"LLM block: credential '{credentials.get('name')}' is a {credentials.get('type')}, "
                    f"but provider '{provider_name}' needs a {provider.credential_type}."
                )
            api_key = str(credentials.get("api_key") or "").strip()
        else:
            api_key = os.environ.get(provider.env_var, "").strip()
        if not api_key:
            raise FatalError(
                f"LLM block: no API key. Select a saved credential in the block, "
                f"or set {provider.env_var} for the worker (workflow-backend/.env)."
            )

        request = LLMRequest(
            model=model,
            prompt=prompt,
            api_key=api_key,
            system_prompt=system_prompt or None,
            temperature=temperature,
            max_output_tokens=max_tokens,
            json_mode=json_mode,
            json_schema=json_schema if json_mode else None,
            timeout_seconds=timeout,
        )

        # urllib is blocking; keep the event loop free while it waits.
        try:
            response = await asyncio.to_thread(provider.generate, request)
        except LLMProviderError as e:
            raise self._classify(e, provider_name, model) from None

        parsed = None
        if json_mode:
            try:
                parsed = json.loads(response.text)
            except json.JSONDecodeError:
                snippet = response.text[:200]
                if response.finish_reason == "max_tokens":
                    raise FatalError(
                        "LLM block: the JSON answer was cut off at max_output_tokens. "
                        f"Raise max_output_tokens. Start of answer: {snippet!r}"
                    ) from None
                raise RetryableError(
                    f"LLM block: JSON mode was requested but the answer isn't valid JSON. "
                    f"Start of answer: {snippet!r}"
                ) from None

        return {
            "text": response.text,
            "json": parsed,
            "finish_reason": response.finish_reason,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            "model": response.model or model,
        }

    @staticmethod
    def _classify(e: LLMProviderError, provider: str, model: str) -> Exception:
        where = f"LLM block ({provider}, model '{model}')"
        if isinstance(e, ProviderHTTPError):
            s = e.status
            if s == 429:
                return RetryableError(f"{where}: rate limited (429). Body: {e.body}", e.retry_after_seconds)
            if s >= 500:
                return RetryableError(f"{where}: server error ({s}). Body: {e.body}", e.retry_after_seconds)
            if e.reason == "invalid_api_key":
                hint = "the API key was rejected"
            else:
                hint = {
                    400: "bad request; check the prompt, settings and json_schema",
                    401: "the API key was rejected",
                    403: "the API key isn't allowed to use this model or API",
                    404: "model not found; check the model name",
                }.get(s, "client error")
            return FatalError(f"{where}: {hint} ({s}). This won't succeed on retry. Body: {e.body}")
        if isinstance(e, ProviderTimeout):
            return RetryableError(f"{where}: {e}")
        if isinstance(e, ProviderConnectionError):
            return RetryableError(f"{where}: {e}")
        if isinstance(e, ContentBlocked):
            return FatalError(f"{where}: {e}. This won't succeed on retry.")
        if isinstance(e, EmptyResponse):
            return FatalError(f"{where}: {e}. This won't succeed on retry.")
        if isinstance(e, MalformedResponse):
            return RetryableError(f"{where}: {e}")
        return FatalError(f"{where}: {e}")
