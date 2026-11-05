"""
Gemini provider: one generateContent call over REST.

Docs: https://ai.google.dev/api/generate-content
The key goes in the x-goog-api-key header, never in the URL.
"""

import json
import os
import re
import urllib.parse

from app.llm.base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ContentBlocked,
    EmptyResponse,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    MalformedResponse,
    ProviderHTTPError,
    ToolCall,
    ToolSpec,
    Transport,
    loads_or_none,
    parse_retry_after,
    truncate_body,
    urllib_transport,
)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# finishReason values that mean the answer was withheld for policy reasons.
BLOCKED_FINISH_REASONS = {
    "SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION",
    "IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT",
}

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)s\s*$")

# A 429 saying "limit: 0" means the key's plan has no quota for this model at
# all, so waiting won't help. "limit: 15" is an ordinary rate limit.
_ZERO_QUOTA = re.compile(r"\blimit:\s*0(?![\d.])")

# The model asked for a function in a way the API couldn't honor. There is
# nothing to read in the answer; a fresh attempt usually works.
MALFORMED_CALL_REASONS = {"MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL"}


class GeminiProvider:
    env_var = "GEMINI_API_KEY"
    # A current fast, stable model (Gemini API docs, Nov 2026).
    default_model = "gemini-3.8-flash"
    # Stable text models, default first (Gemini API models and pricing docs, Nov 2026).
    models = [
        {"label": "Gemini 3.8 Flash", "value": "gemini-3.8-flash"},
        {"label": "Gemini 3.6 Flash", "value": "gemini-3.6-flash"},
        {"label": "Gemini 3.5 Flash-Lite", "value": "gemini-3.5-flash-lite"},
        {"label": "Gemini 3.1 Flash-Lite", "value": "gemini-3.1-flash-lite"},
        {"label": "Gemini 4 Argon (paid plan only)", "value": "gemini-4-argon"},
    ]
    credential_type = "gemini_api_key"
    credential_label = "Gemini API key"

    def __init__(self, transport: Transport | None = None, base_url: str | None = None):
        self.transport = transport or urllib_transport
        # GEMINI_BASE_URL exists for tests and network-failure drills.
        self.base_url = (base_url or os.environ.get("GEMINI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")

    # ── request ─────────────────────────────────────────────────────── #

    def build_body(self, req: LLMRequest) -> dict:
        body: dict = {"contents": [{"role": "user", "parts": [{"text": req.prompt}]}]}
        if req.system_prompt:
            body["systemInstruction"] = {"parts": [{"text": req.system_prompt}]}

        gen: dict = {}
        if req.temperature is not None:
            gen["temperature"] = req.temperature
        if req.max_output_tokens is not None:
            gen["maxOutputTokens"] = req.max_output_tokens
        if req.json_mode:
            gen["responseMimeType"] = "application/json"
            if req.json_schema:
                gen["responseSchema"] = req.json_schema
        if gen:
            body["generationConfig"] = gen
        return body

    def url_for(self, model: str) -> str:
        model = model.strip().removeprefix("models/")
        return f"{self.base_url}/models/{urllib.parse.quote(model, safe='.-_')}:generateContent"

    def generate(self, req: LLMRequest) -> LLMResponse:
        data = self._post(req.model, req.api_key, self.build_body(req), req.timeout_seconds)
        return self.parse_response(data, req.model)

    # ── tool calling ────────────────────────────────────────────────── #
    # FunctionDeclaration / functionCall / functionResponse per
    # https://ai.google.dev/api/caching. Model turns go back exactly as
    # received, so opaque parts (thoughtSignature) survive multi-turn calls.

    @staticmethod
    def tool_declarations(tools: list[ToolSpec]) -> list[dict]:
        if not tools:
            return []
        return [{
            "functionDeclarations": [
                {"name": t.name, "description": t.description, "parametersJsonSchema": t.parameters}
                for t in tools
            ]
        }]

    @staticmethod
    def message_content(m: ChatMessage) -> dict:
        if m.role == "user":
            return {"role": "user", "parts": [{"text": m.text}]}
        if m.role == "model":
            if isinstance(m.raw, dict) and m.raw.get("parts"):
                return {**m.raw, "role": "model"}
            parts: list[dict] = [{"text": m.text}] if m.text else []
            for c in m.tool_calls:
                fc: dict = {"name": c.name, "args": c.args}
                if c.provider_id:
                    fc["id"] = c.provider_id
                parts.append({"functionCall": fc})
            return {"role": "model", "parts": parts}
        if m.role == "tool":
            parts = []
            for r in m.tool_results:
                fr: dict = {"name": r["name"], "response": r["response"]}
                if r.get("provider_id"):
                    fr["id"] = r["provider_id"]
                parts.append({"functionResponse": fr})
            return {"role": "user", "parts": parts}
        raise ValueError(f"unknown message role {m.role}")

    def build_chat_body(self, req: ChatRequest) -> dict:
        body: dict = {"contents": [self.message_content(m) for m in req.messages]}
        if req.system_prompt:
            body["systemInstruction"] = {"parts": [{"text": req.system_prompt}]}
        tools = self.tool_declarations(req.tools)
        if tools:
            body["tools"] = tools
        if req.temperature is not None:
            body["generationConfig"] = {"temperature": req.temperature}
        return body

    def chat(self, req: ChatRequest) -> ChatResponse:
        data = self._post(req.model, req.api_key, self.build_chat_body(req), req.timeout_seconds)
        return self.parse_chat_response(data, req.model)

    @classmethod
    def parse_chat_response(cls, data: dict, requested_model: str) -> ChatResponse:
        cand = (data.get("candidates") or [{}])[0] if isinstance(data.get("candidates"), list) else {}
        if isinstance(cand, dict) and cand.get("finishReason") in MALFORMED_CALL_REASONS:
            raise MalformedResponse(
                f"the model produced an unusable function call (finishReason={cand['finishReason']})"
            )
        # Same blocking checks and usage accounting as a plain generate call.
        plain = cls.parse_response(data, requested_model)
        content = cand.get("content") or {}
        parts = [p for p in content.get("parts") or [] if isinstance(p, dict)]
        calls: list[ToolCall] = []
        for i, part in enumerate(parts):
            fc = part.get("functionCall")
            if not isinstance(fc, dict):
                continue
            args = fc.get("args")
            provider_id = fc.get("id") if isinstance(fc.get("id"), str) and fc.get("id") else None
            calls.append(ToolCall(
                id=provider_id or f"call_{i}",
                name=str(fc.get("name") or ""),
                args=args if isinstance(args, dict) else {},
                provider_id=provider_id,
            ))
        if not calls and not plain.text and plain.finish_reason != "max_tokens":
            raise EmptyResponse("the model returned neither text nor a function call")
        return ChatResponse(
            text=plain.text,
            tool_calls=calls,
            raw={"role": "model", "parts": content.get("parts") or []},
            finish_reason=plain.finish_reason,
            usage=plain.usage,
            model=plain.model,
        )

    # ── transport ───────────────────────────────────────────────────── #

    def _post(self, model: str, api_key: str, body: dict, timeout: float) -> dict:
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }
        payload = json.dumps(body).encode("utf-8")
        resp = self.transport(self.url_for(model), headers, payload, timeout)

        if not 200 <= resp.status < 300:
            text = resp.body.decode("utf-8", errors="replace")
            retry_after = parse_retry_after(
                next((v for k, v in resp.headers.items() if k.lower() == "retry-after"), None)
            )
            err_json = loads_or_none(resp.body)
            if retry_after is None:
                retry_after = _retry_delay_from_body(err_json)
            raise ProviderHTTPError(
                resp.status, truncate_body(text, api_key), retry_after, _error_reason(err_json, resp.status)
            )

        data = loads_or_none(resp.body)
        if not isinstance(data, dict):
            raise MalformedResponse(
                "response body is not a JSON object: "
                + truncate_body(resp.body.decode("utf-8", errors="replace"), api_key)
            )
        return data

    # ── response ────────────────────────────────────────────────────── #

    @staticmethod
    def parse_response(data: dict, requested_model: str) -> LLMResponse:
        block_reason = (data.get("promptFeedback") or {}).get("blockReason")
        if block_reason:
            raise ContentBlocked(f"the prompt was blocked (promptFeedback.blockReason={block_reason})")

        candidates = data.get("candidates") or []
        if not candidates:
            raise EmptyResponse("the response had no candidates")

        cand = candidates[0]
        raw_reason = cand.get("finishReason")
        if raw_reason in BLOCKED_FINISH_REASONS:
            raise ContentBlocked(f"the answer was withheld (finishReason={raw_reason})")

        parts = (cand.get("content") or {}).get("parts") or []
        # Thought summaries are not part of the answer.
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))

        um = data.get("usageMetadata") or {}
        prompt_tokens = um.get("promptTokenCount")
        # Thinking tokens are billed as output, so count them there; then
        # input + output adds up to totalTokenCount.
        out_parts = [um.get("candidatesTokenCount"), um.get("thoughtsTokenCount")]
        output_tokens = sum(n for n in out_parts if n) if any(n is not None for n in out_parts) else None
        usage = LLMUsage(
            input_tokens=prompt_tokens,
            output_tokens=output_tokens,
            total_tokens=um.get("totalTokenCount"),
        )
        return LLMResponse(
            text=text,
            finish_reason=raw_reason.lower() if isinstance(raw_reason, str) else None,
            usage=usage,
            model=data.get("modelVersion") or requested_model,
        )


def _retry_delay_from_body(data) -> float | None:
    """Google errors carry a RetryInfo detail like {"retryDelay": "13s"}."""
    for d in _error_details(data):
        if isinstance(d.get("retryDelay"), str):
            m = _DURATION.match(d["retryDelay"])
            if m:
                return float(m.group(1))
    return None


def _error_object(data) -> dict:
    error = data.get("error") if isinstance(data, dict) else None
    return error if isinstance(error, dict) else {}


def _error_details(data) -> list:
    details = _error_object(data).get("details") or []
    return [d for d in details if isinstance(d, dict)] if isinstance(details, list) else []


def _error_reason(data, status: int) -> str | None:
    """Gemini reports a bad key as 400 with ErrorInfo reason API_KEY_INVALID,
    unmet billing prerequisites as 400 FAILED_PRECONDITION, and a model the
    plan doesn't include as 429 with "limit: 0" in the message."""
    reasons = {d.get("reason") for d in _error_details(data)}
    if "API_KEY_INVALID" in reasons:
        return "invalid_api_key"

    error = _error_object(data)
    # "status" is the older error shape, "code" the current one.
    codes = {str(error.get("status")).lower(), str(error.get("code")).lower()}
    if "failed_precondition" in codes:
        return "billing_required"
    if status == 429 and _ZERO_QUOTA.search(str(error.get("message") or "")):
        return "model_not_on_plan"
    return None
