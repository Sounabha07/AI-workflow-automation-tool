"""LLM block + Gemini provider, against a fake transport: no network."""

import json

import pytest

from app.llm.base import ProviderConnectionError, ProviderTimeout, TransportResponse
from app.llm.gemini import GeminiProvider
from app.validation import validate_definition
from blocks.base import FatalError, RetryableError
from blocks.llm import LLMBlock
from tests.conftest import block

KEY = "AIza-test-key-0123456789"


class FakeTransport:
    """Records each call and replays queued responses (or raises queued errors)."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": json.loads(body), "timeout": timeout})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def ok(text="Hello", finish="STOP", usage=None, model="gemini-3.8-flash-001", **extra):
    data = {
        "candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish}],
        "usageMetadata": usage if usage is not None else {
            "promptTokenCount": 7, "candidatesTokenCount": 3, "totalTokenCount": 10,
        },
        "modelVersion": model,
        **extra,
    }
    return TransportResponse(200, {"Content-Type": "application/json"}, json.dumps(data).encode())


def err(status, body=None, headers=None):
    body = body if body is not None else {"error": {"code": status, "message": "nope", "status": "X"}}
    return TransportResponse(status, headers or {}, json.dumps(body).encode())


def make(*responses):
    t = FakeTransport(*responses)
    return LLMBlock(providers={"gemini": GeminiProvider(transport=t, base_url="https://fake.test/v1beta")}), t


CREDS = {"api_key": KEY, "type": "gemini_api_key", "name": "Client key"}


def cfg(**over):
    return {"provider": "gemini", "model": "gemini-3.8-flash", "prompt": "Say hi", **over}


@pytest.fixture(autouse=True)
def no_env_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


# ── request shape ───────────────────────────────────────────────────── #

async def test_request_body_headers_and_url():
    blk, t = make(ok())
    await blk.execute(cfg(system_prompt="Be brief.", temperature=0.2, max_output_tokens=50, timeout_seconds=9), {}, CREDS)
    call = t.calls[0]
    assert call["url"] == "https://fake.test/v1beta/models/gemini-3.8-flash:generateContent"
    assert KEY not in call["url"]
    assert call["headers"]["x-goog-api-key"] == KEY
    assert call["timeout"] == 9
    assert call["body"] == {
        "contents": [{"role": "user", "parts": [{"text": "Say hi"}]}],
        "systemInstruction": {"parts": [{"text": "Be brief."}]},
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 50},
    }


async def test_json_mode_sends_mime_type_and_schema():
    schema = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}
    blk, t = make(ok(text='{"city": "Kolkata"}'))
    await blk.execute(cfg(response_format="json", json_schema=schema), {}, CREDS)
    gen = t.calls[0]["body"]["generationConfig"]
    assert gen["responseMimeType"] == "application/json"
    assert gen["responseSchema"] == schema
    assert "systemInstruction" not in t.calls[0]["body"]


async def test_text_mode_ignores_leftover_schema_and_omits_unset_options():
    blk, t = make(ok())
    await blk.execute(cfg(temperature=None, json_schema={"type": "object"}), {}, CREDS)
    assert "generationConfig" not in t.calls[0]["body"]


async def test_env_key_used_when_no_credential(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key-xyz")
    blk, t = make(ok())
    await blk.execute(cfg(), {}, None)
    assert t.calls[0]["headers"]["x-goog-api-key"] == "env-key-xyz"


async def test_saved_credential_wins_over_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key-xyz")
    blk, t = make(ok())
    await blk.execute(cfg(), {}, CREDS)
    assert t.calls[0]["headers"]["x-goog-api-key"] == KEY


async def test_credential_of_another_type_is_fatal():
    blk, t = make()
    with pytest.raises(FatalError, match="needs a gemini_api_key"):
        await blk.execute(cfg(), {}, {**CREDS, "type": "openai_api_key"})
    assert t.calls == []


# ── response parsing ────────────────────────────────────────────────── #

async def test_text_response_and_usage_mapping():
    blk, _ = make(ok(text="Hi there", usage={
        "promptTokenCount": 11, "candidatesTokenCount": 4, "thoughtsTokenCount": 20, "totalTokenCount": 35,
    }))
    out = await blk.execute(cfg(), {}, CREDS)
    assert out == {
        "text": "Hi there",
        "json": None,
        "finish_reason": "stop",
        "usage": {"input_tokens": 11, "output_tokens": 24, "total_tokens": 35},
        "model": "gemini-3.8-flash-001",
    }


async def test_thought_parts_are_not_part_of_the_text():
    resp = {
        "candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": "Answer"}]},
                        "finishReason": "STOP"}],
    }
    blk, _ = make(TransportResponse(200, {}, json.dumps(resp).encode()))
    out = await blk.execute(cfg(), {}, CREDS)
    assert out["text"] == "Answer"
    assert out["usage"] == {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    assert out["model"] == "gemini-3.8-flash"  # no modelVersion: falls back to the requested name


async def test_json_response_is_parsed():
    blk, _ = make(ok(text='{"city": "Kolkata", "n": 2}'))
    out = await blk.execute(cfg(response_format="json"), {}, CREDS)
    assert out["json"] == {"city": "Kolkata", "n": 2}
    assert out["text"] == '{"city": "Kolkata", "n": 2}'


async def test_max_tokens_is_success_with_finish_reason():
    blk, _ = make(ok(text="Once upon a", finish="MAX_TOKENS"))
    out = await blk.execute(cfg(max_output_tokens=3), {}, CREDS)
    assert out["finish_reason"] == "max_tokens"
    assert out["text"] == "Once upon a"


# ── error classification ────────────────────────────────────────────── #

@pytest.mark.parametrize("status", [429, 500, 503])
async def test_retryable_statuses(status):
    blk, _ = make(err(status))
    with pytest.raises(RetryableError, match=f"\\({status}\\)"):
        await blk.execute(cfg(), {}, CREDS)


async def test_retry_after_header_is_honored():
    blk, _ = make(err(429, headers={"Retry-After": "17"}))
    with pytest.raises(RetryableError) as e:
        await blk.execute(cfg(), {}, CREDS)
    assert e.value.retry_after_seconds == 17


async def test_retry_delay_from_error_body():
    body = {"error": {"code": 429, "message": "quota", "details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "23s"}]}}
    blk, _ = make(err(429, body))
    with pytest.raises(RetryableError) as e:
        await blk.execute(cfg(), {}, CREDS)
    assert e.value.retry_after_seconds == 23


@pytest.mark.parametrize("exc", [ProviderTimeout("timed out after 60s"), ProviderConnectionError("network error: refused")])
async def test_timeouts_and_connection_errors_are_retryable(exc):
    blk, _ = make(exc)
    with pytest.raises(RetryableError):
        await blk.execute(cfg(), {}, CREDS)


async def test_invalid_json_in_json_mode_is_retryable():
    blk, _ = make(ok(text="Sure! Here is the JSON: {"))
    with pytest.raises(RetryableError, match="isn't valid JSON"):
        await blk.execute(cfg(response_format="json"), {}, CREDS)


async def test_truncated_json_at_max_tokens_is_fatal():
    blk, _ = make(ok(text='{"city": "Kol', finish="MAX_TOKENS"))
    with pytest.raises(FatalError, match="max_output_tokens"):
        await blk.execute(cfg(response_format="json"), {}, CREDS)


@pytest.mark.parametrize("status,hint", [
    (400, "bad request"), (401, "rejected"), (403, "isn't allowed"), (404, "model not found"),
])
async def test_fatal_statuses(status, hint):
    blk, _ = make(err(status))
    with pytest.raises(FatalError, match=hint):
        await blk.execute(cfg(), {}, CREDS)


async def test_invalid_key_reported_as_rejected_key():
    body = {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                      "status": "INVALID_ARGUMENT",
                      "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]}}
    blk, _ = make(err(400, body))
    with pytest.raises(FatalError, match="API key was rejected"):
        await blk.execute(cfg(), {}, CREDS)


async def test_prompt_blocked_is_fatal():
    resp = {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}
    blk, _ = make(TransportResponse(200, {}, json.dumps(resp).encode()))
    with pytest.raises(FatalError, match="blockReason=SAFETY"):
        await blk.execute(cfg(), {}, CREDS)


async def test_answer_stopped_for_safety_is_fatal():
    blk, _ = make(ok(text="", finish="SAFETY"))
    with pytest.raises(FatalError, match="finishReason=SAFETY"):
        await blk.execute(cfg(), {}, CREDS)


async def test_empty_candidates_is_fatal():
    blk, _ = make(TransportResponse(200, {}, b'{"candidates": []}'))
    with pytest.raises(FatalError, match="no candidates"):
        await blk.execute(cfg(), {}, CREDS)


async def test_missing_key_fails_fast_without_calling_out():
    blk, t = make()
    with pytest.raises(FatalError, match="Select a saved credential.*GEMINI_API_KEY"):
        await blk.execute(cfg(), {}, None)
    assert t.calls == []


async def test_error_body_is_truncated_and_key_scrubbed():
    body = {"error": {"message": f"echo {KEY} " + "x" * 5000}}
    blk, _ = make(err(500, body))
    with pytest.raises(RetryableError) as e:
        await blk.execute(cfg(), {}, CREDS)
    msg = str(e.value)
    assert KEY not in msg
    assert "[redacted]" in msg and msg.endswith("… (truncated)")


async def test_key_never_in_any_error_message():
    cases = [err(401), err(429), ok(text="x", finish="SAFETY"), ProviderConnectionError("refused"),
             TransportResponse(200, {}, b"<html>")]
    for r in cases:
        blk, _ = make(r)
        with pytest.raises((FatalError, RetryableError)) as e:
            await blk.execute(cfg(), {}, CREDS)
        assert KEY not in str(e.value)


async def test_unknown_provider_is_fatal():
    with pytest.raises(FatalError, match="unknown provider 'openai'"):
        await LLMBlock().execute(cfg(provider="openai"), {}, CREDS)


@pytest.mark.parametrize("over,match", [
    ({"prompt": "  "}, "prompt"),
    ({"temperature": 3}, "between 0 and 2"),
    ({"max_output_tokens": 0}, "positive whole number"),
    ({"response_format": "xml"}, "response_format"),
])
async def test_block_rechecks_resolved_values(over, match):
    blk, t = make()
    with pytest.raises(FatalError, match=match):
        await blk.execute(cfg(**over), {}, CREDS)
    assert t.calls == []


def test_schema_has_a_credential_picker_and_no_key_field():
    fields = {f["name"]: f for f in LLMBlock.schema["fields"]}
    assert "api_key" not in fields
    assert fields["credential"]["type"] == "credential"
    assert fields["credential"]["credential_types"] == ["gemini_api_key"]


# ── validation ─────────────────────────────────────────────────────── #

def _wf(**config):
    return {"blocks": {
        "trigger": block("manual_trigger", ["llm_1"]),
        "llm_1": block("llm", [], ["trigger"], {"provider": "gemini", "prompt": "Hi", **config}),
    }}


def test_valid_llm_config():
    assert validate_definition(_wf()) == []
    assert validate_definition(_wf(temperature="{{ trigger.t }}", response_format="json",
                                   json_schema={"type": "object"})) == []
    assert validate_definition(_wf(json_schema={})) == []  # empty schema in text mode is fine
    assert validate_definition(_wf(credential="7d0f4a1e-2b3c-4d5e-8f90-a1b2c3d4e5f6")) == []


@pytest.mark.parametrize("config,fragment", [
    ({"prompt": ""}, "prompt can't be empty"),
    ({"prompt": "   "}, "prompt can't be empty"),
    ({"temperature": 2.5}, "temperature must be a number from 0 to 2"),
    ({"temperature": -0.1}, "temperature must be"),
    ({"temperature": "hot"}, "temperature must be"),
    ({"max_output_tokens": -5}, "positive whole number"),
    ({"response_format": "yaml"}, "response format"),
    ({"json_schema": {"type": "object"}}, "only used when the response format is 'json'"),
    ({"response_format": "json", "json_schema": [1, 2]}, "must be a JSON object"),
    ({"response_format": "json", "json_schema": "not json"}, "must be a JSON object"),
    ({"provider": "openai"}, "unknown provider 'openai'"),
    ({"api_key": "AIza..."}, "API keys can't be stored in a workflow"),
    ({"credential": "not-a-uuid"}, "must be a saved credential's id"),
])
def test_invalid_llm_config(config, fragment):
    problems = validate_definition(_wf(**config))
    assert any(fragment in p for p in problems), problems
