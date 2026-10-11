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
    ContentBlocked,
    EmptyResponse,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    MalformedResponse,
    ProviderHTTPError,
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


class GeminiProvider:
    env_var = "GEMINI_API_KEY"
    # A current fast, stable model (Gemini API docs, Oct 2026). Free text in the
    # block, so newer names work without a code change.
    default_model = "gemini-3.8-flash"

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
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": req.api_key,
        }
        payload = json.dumps(self.build_body(req)).encode("utf-8")
        resp = self.transport(self.url_for(req.model), headers, payload, req.timeout_seconds)

        if not 200 <= resp.status < 300:
            text = resp.body.decode("utf-8", errors="replace")
            retry_after = parse_retry_after(
                next((v for k, v in resp.headers.items() if k.lower() == "retry-after"), None)
            )
            err_json = loads_or_none(resp.body)
            if retry_after is None:
                retry_after = _retry_delay_from_body(err_json)
            raise ProviderHTTPError(
                resp.status, truncate_body(text, req.api_key), retry_after, _error_reason(err_json)
            )

        data = loads_or_none(resp.body)
        if not isinstance(data, dict):
            raise MalformedResponse(
                "response body is not a JSON object: "
                + truncate_body(resp.body.decode("utf-8", errors="replace"), req.api_key)
            )
        return self.parse_response(data, req.model)

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


def _error_details(data) -> list:
    if not isinstance(data, dict):
        return []
    details = (data.get("error") or {}).get("details") or []
    return [d for d in details if isinstance(d, dict)] if isinstance(details, list) else []


def _error_reason(data) -> str | None:
    """Gemini reports a bad key as 400 with ErrorInfo reason API_KEY_INVALID."""
    reasons = {d.get("reason") for d in _error_details(data)}
    if "API_KEY_INVALID" in reasons:
        return "invalid_api_key"
    return None
