"""Agent block: the loop, the tool request builder, checkpoint resume and the
Gemini tool-calling adapter. The scripted provider stands in for the model
and a fake executor for HTTP; nothing touches the network or a database."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.agent.http_tool import MASK, ToolArgumentError, build_request, call_tool
from app.agent.loop import NUDGE, UNKNOWN_OUTCOME, AgentRun, AgentSettings, AgentStopped, AgentTool
from app.agent.steps import MemoryStepStore, StepRow
from app.agent.tools import side_effects, tool_spec, unsupported_keywords
from app.llm.base import ChatMessage, ChatRequest, ToolCall, ToolSpec
from app.llm.gemini import GeminiProvider
from app.llm.scripted import ScriptedProvider
from blocks.base import FatalError, RetryableError

RUN, BLOCK = "run-1", "agent_1"
SECRET = "sk-test-very-secret-123"


def http_tool_cfg(method="GET", url="http://api.test/items", name="get_items", params=None, **extra):
    return {
        "method": method, "url": url, "authentication": "none", "timeout_seconds": 10,
        "tool_name": name, "tool_description": f"The {name} tool, used by the tests here.",
        "tool_parameters": params or {"type": "object", "properties": {"q": {"type": "string"}}},
        **extra,
    }


class FakeHTTP:
    """Executor stand-in: records each request, answers from `responses`
    (a callable or a list consumed in order), default 200 echo."""

    def __init__(self, responses=None):
        self.calls: list[dict] = []
        self.responses = responses

    async def __call__(self, exec_config: dict) -> dict:
        self.calls.append(exec_config)
        r = self.responses
        if callable(r):
            r = r(exec_config)
        elif isinstance(r, list):
            r = r.pop(0)
        if isinstance(r, Exception):
            raise r
        return r or {"data": {"url": exec_config["url"], "auth": f"Bearer {SECRET}"}, "statusCode": 200, "headers": {}}


def make_run(script, tools=None, store=None, http=None, **settings):
    tools = tools if tools is not None else [http_tool_cfg()]
    agent_tools = [AgentTool(f"t{i}", tool_spec(c), c, side_effects(c)) for i, c in enumerate(tools)]
    s = AgentSettings(provider=ScriptedProvider(), provider_name="scripted", model="scripted", api_key="",
                      task="do it", options={"script": script}, **settings)
    return AgentRun(s, agent_tools, store=store or MemoryStepStore(), run_id=RUN, block_id=BLOCK,
                    executor=http or FakeHTTP())


SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


# ── the loop ─────────────────────────────────────────────────────────── #

async def test_ends_on_text_without_output_schema():
    out = await make_run([{"text": "done"}]).run()
    assert out["final"] == "done" and out["text"] == "done"
    assert out["stop_reason"] == "finished" and out["iterations"] == 1 and out["tool_calls"] == 0
    assert out["usage"]["total_tokens"] == 15


async def test_finish_with_a_valid_schema():
    out = await make_run([{"finish": {"answer": "42"}}], output_schema=SCHEMA).run()
    assert out["final"] == {"answer": "42"} and out["iterations"] == 1


async def test_invalid_finish_is_sent_back_and_corrected():
    run = make_run([{"finish": {"answer": 1}}, {"finish": {"answer": "ok"}}], output_schema=SCHEMA)
    out = await run.run()
    assert out["final"] == {"answer": "ok"} and out["iterations"] == 2
    bad = next(t for t in out["trace"] if t["kind"] == "tool")
    assert bad["status"] == "failed" and "output schema" in bad["response"]["error"]


async def test_text_without_finish_is_corrected_once():
    run = make_run([{"text": "it's 42"}, {"finish": {"answer": "42"}}], output_schema=SCHEMA)
    out = await run.run()
    assert out["final"] == {"answer": "42"} and out["iterations"] == 2
    assert [t.get("nudge") for t in out["trace"] if t["kind"] == "model"] == [NUDGE, None]
    assert out["text"] == "it's 42"


async def test_max_iterations_stops_with_trace():
    with pytest.raises(AgentStopped) as e:
        await make_run([{"tool_calls": [{"name": "get_items", "args": {}}]}], max_iterations=2).run()
    d = e.value.detail
    assert d["stop_reason"] == "max_iterations" and d["iterations"] == 2 and len(d["trace"]) == 4
    assert isinstance(e.value, FatalError)


async def test_token_budget_stops():
    with pytest.raises(AgentStopped) as e:
        await make_run([{"tool_calls": [{"name": "get_items", "args": {}}], "usage": {"total_tokens": 600}}],
                       max_total_tokens=1000).run()
    assert e.value.detail["stop_reason"] == "budget" and e.value.detail["usage"]["total_tokens"] == 1200


async def test_total_timeout_counts_from_the_first_attempt():
    run = make_run([{"text": "x"}], timeout_seconds=60)
    run.deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(AgentStopped) as e:
        await run.run()
    assert e.value.detail["stop_reason"] == "timeout"


async def test_unknown_tool_and_invalid_args_are_observations():
    http = FakeHTTP()
    run = make_run([
        {"tool_calls": [{"name": "nope", "args": {}}, {"name": "get_items", "args": {"q": 5}}]},
        {"text": "gave up"},
    ], http=http)
    out = await run.run()
    tools = [t for t in out["trace"] if t["kind"] == "tool"]
    assert "no tool named 'nope'" in tools[0]["response"]["error"] or "no tool named 'nope'" in tools[1]["response"]["error"]
    assert any("invalid arguments" in t["response"]["error"] for t in tools)
    assert http.calls == [] and out["tool_calls"] == 0
    # Both results went back to the model in one tool message.
    assert [len(m.tool_results) for m in run.messages if m.role == "tool"] == [2]


async def test_parallel_calls_run_concurrently():
    import asyncio

    in_flight, peak = 0, 0

    async def slow(exec_config):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return {"data": {"ok": True}, "statusCode": 200}

    out = await make_run([
        {"tool_calls": [{"name": "get_items", "args": {"q": "a"}}, {"name": "get_items", "args": {"q": "b"}}]},
        {"text": "done"},
    ], http=slow).run()
    assert peak == 2 and out["tool_calls"] == 2


async def test_a_failing_tool_is_an_observation_not_a_failure():
    http = FakeHTTP([FatalError("client error (404)", status=404, body="not here")])
    out = await make_run([{"tool_calls": [{"name": "get_items", "args": {}}]}, {"text": "no luck"}], http=http).run()
    t = next(t for t in out["trace"] if t["kind"] == "tool")
    assert t["status"] == "failed"
    assert t["response"] == {"error": "client error (404)", "status": 404, "body_snippet": "not here", "retryable": False}


async def test_retryable_model_error_raises_retryable():
    store = MemoryStepStore()
    with pytest.raises(RetryableError):
        await make_run([{"tool_calls": [{"name": "get_items", "args": {}}]}, {"error": 503}], store=store).run()
    rows = await store.load(RUN, BLOCK)
    assert [(r.kind, r.status) for r in rows] == [("model", "completed"), ("tool", "completed"), ("model", "failed")]


# ── resume from the checkpoint ───────────────────────────────────────── #

async def test_resume_replays_completed_steps_and_carries_the_count():
    store, http = MemoryStepStore(), FakeHTTP()
    script = [{"tool_calls": [{"name": "get_items", "args": {"q": "a"}}]}, {"error": 503}, {"text": "done"}]
    with pytest.raises(RetryableError):
        await make_run(script, store=store, http=http).run()
    assert len(http.calls) == 1
    out = await make_run(script, store=store, http=http).run()
    assert len(http.calls) == 1  # never re-run
    assert out["iterations"] == 2 and out["usage"]["total_tokens"] == 30
    assert all(t["replayed"] for t in out["trace"][:3]) and not out["trace"][-1]["replayed"]


async def _crashed_mid_call(store, method):
    """A checkpoint as a crash leaves it: the model asked for one call, its
    'started' row is written, nothing after that."""
    await store.insert(RUN, BLOCK, StepRow(
        step_index=0, kind="model", status="completed",
        result={"text": "", "tool_calls": [{"id": "call_0", "name": "get_items", "args": {"q": "x"}}]},
        provider_payload={"role": "model", "parts": [{"functionCall": {"name": "get_items", "args": {"q": "x"}}}]},
        usage={"total_tokens": 15},
    ))
    await store.insert(RUN, BLOCK, StepRow(
        step_index=0, kind="tool", status="started", tool_call_id="call_0", tool_name="get_items",
        side_effects=method != "GET", args={"q": "x"},
    ))


async def test_resume_reruns_an_unfinished_safe_call():
    store, http = MemoryStepStore(), FakeHTTP()
    await _crashed_mid_call(store, "GET")
    run = make_run([{"error": 503}, {"text": "done"}], tools=[http_tool_cfg("GET")], store=store, http=http)
    out = await run.run()
    assert len(http.calls) == 1 and out["final"] == "done" and out["iterations"] == 2
    tool = next(t for t in out["trace"] if t["kind"] == "tool")
    assert tool["status"] == "completed" and not tool["outcome_unknown"]


async def test_resume_never_reruns_an_unfinished_side_effecting_call():
    store, http = MemoryStepStore(), FakeHTTP()
    await _crashed_mid_call(store, "POST")
    run = make_run([{"error": 503}, {"text": "checked"}], tools=[http_tool_cfg("POST")], store=store, http=http)
    out = await run.run()
    assert http.calls == []
    tool = next(t for t in out["trace"] if t["kind"] == "tool")
    assert tool["status"] == "failed" and tool["outcome_unknown"]
    sent = next(m for m in run.messages if m.role == "tool").tool_results[0]["response"]
    assert sent["error"] == UNKNOWN_OUTCOME


async def test_resume_finishes_without_a_model_call_if_finish_was_accepted():
    store = MemoryStepStore()
    await make_run([{"finish": {"answer": "a"}}], store=store, output_schema=SCHEMA).run()
    out = await make_run([{"error": 500}], store=store, output_schema=SCHEMA).run()
    assert out["final"] == {"answer": "a"} and out["iterations"] == 1


# ── request building ─────────────────────────────────────────────────── #

def test_get_args_become_query_params_and_none_is_dropped():
    cfg = http_tool_cfg("GET", "http://api.test/runs?fixed=1", send_query_params=True,
                        query_params=[{"key": "page", "value": "1"}])
    exec_cfg, summary = build_request(cfg, {"status": "failed", "limit": 5, "flag": True, "skip": None})
    assert exec_cfg["query_params"] == [
        {"key": "page", "value": "1"}, {"key": "status", "value": "failed"},
        {"key": "limit", "value": "5"}, {"key": "flag", "value": "true"},
    ]
    assert exec_cfg["url"] == "http://api.test/runs?fixed=1" and not exec_cfg["send_body"]
    assert "body" not in summary


def test_post_args_become_the_json_body_and_static_fields_win():
    cfg = http_tool_cfg("POST", "http://api.test/notes", tool_static_fields={"source": "fixed"})
    exec_cfg, summary = build_request(cfg, {"note": "hi", "source": "model"})
    assert exec_cfg["send_body"] and exec_cfg["body_content_type"] == "json"
    assert exec_cfg["body_json"] == {"note": "hi", "source": "fixed"} == summary["body"]


@pytest.mark.parametrize("value, encoded", [("../x", "..%2Fx"), ("a/b", "a%2Fb"), ("a b", "a%20b"),
                                            ("..", "%2E%2E"), (7, "7")])
def test_path_params_are_encoded(value, encoded):
    exec_cfg, _ = build_request(http_tool_cfg(url="http://api.test/items/{id}/x"), {"id": value, "q": "z"})
    assert exec_cfg["url"] == f"http://api.test/items/{encoded}/x"
    assert exec_cfg["query_params"] == [{"key": "q", "value": "z"}]  # the path param left the payload


def test_missing_path_param_is_an_argument_error():
    with pytest.raises(ToolArgumentError, match="missing required path parameter"):
        build_request(http_tool_cfg(url="http://api.test/items/{id}"), {})


@pytest.mark.parametrize("url", ["http://{host}/x", "http://api.test:{port}/x", "{scheme}://api.test/x"])
def test_args_cant_change_scheme_host_or_port(url):
    with pytest.raises(ToolArgumentError, match="scheme, host or port"):
        build_request(http_tool_cfg(url=url), {"host": "evil.test", "port": "1", "scheme": "https"})


def test_side_effects_auto_by_method():
    assert not side_effects({"method": "GET"}) and not side_effects({"method": "HEAD"})
    assert side_effects({"method": "POST"}) and side_effects({"method": "DELETE"})
    assert side_effects({"method": "GET", "tool_side_effects": "true"})
    assert not side_effects({"method": "POST", "tool_side_effects": "false"})


async def test_inline_retry_only_when_side_effect_free():
    flaky = lambda: FakeHTTP([RetryableError("server error (503)", status=503), None])  # noqa: E731
    http = flaky()
    r = await call_tool(http_tool_cfg("GET"), {}, timeout_seconds=5, max_result_chars=100, executor=http,
                        backoff_seconds=0)
    assert r.ok and r.attempts == 2 and len(http.calls) == 2
    http = flaky()
    r = await call_tool(http_tool_cfg("POST"), {}, timeout_seconds=5, max_result_chars=100, executor=http,
                        backoff_seconds=0)
    assert not r.ok and r.attempts == 1 and len(http.calls) == 1 and r.response["retryable"] is True


async def test_non_retryable_errors_are_not_retried_inline():
    http = FakeHTTP([FatalError("client error (400)", status=400, body="bad")])
    r = await call_tool(http_tool_cfg("GET"), {}, timeout_seconds=5, max_result_chars=100, executor=http)
    assert not r.ok and len(http.calls) == 1


async def test_results_are_truncated_for_the_model_but_kept_whole():
    http = FakeHTTP([{"data": {"text": "x" * 500}, "statusCode": 200}])
    r = await call_tool(http_tool_cfg(), {}, timeout_seconds=5, max_result_chars=100, executor=http)
    assert r.response["truncated"] and "truncated: showing 100 of" in r.response["result"]
    assert r.full_result["data"]["text"] == "x" * 500


async def test_output_mapping_selects_fields():
    http = FakeHTTP([{"data": {"items": [{"id": 7, "name": "a"}], "total": 1}, "statusCode": 200}])
    cfg = http_tool_cfg(output_mapping=[{"key": "first", "value": "items.0.id"}, {"key": "n", "value": "total"}])
    r = await call_tool(cfg, {}, timeout_seconds=5, max_result_chars=100, executor=http)
    assert r.response == {"result": {"first": 7, "n": 1}}


# ── masking ──────────────────────────────────────────────────────────── #

async def test_credentials_never_reach_the_trace():
    cfg = http_tool_cfg(authentication="bearer", bearer_token=SECRET, send_headers=True,
                        headers=[{"key": "X-Api-Key", "value": "hdr-secret-999"}])
    out = await make_run([{"tool_calls": [{"name": "get_items", "args": {"q": "a"}}]}, {"text": "ok"}],
                         tools=[cfg]).run()
    blob = json.dumps(out, default=str)
    assert SECRET not in blob and "hdr-secret-999" not in blob
    req = next(t for t in out["trace"] if t["kind"] == "tool")["request"]
    assert req["headers"] == {"X-Api-Key": MASK, "Authorization": MASK}


def test_apikey_in_query_is_masked_in_the_summary():
    cfg = http_tool_cfg(authentication="apikey", apikey_location="query", apikey_name="key", apikey_value="qsecret-abc")
    _, summary = build_request(cfg, {"q": "a"})
    assert summary["query"]["key"] == MASK and "qsecret-abc" not in json.dumps(summary)


# ── Gemini adapter ───────────────────────────────────────────────────── #

def test_gemini_tool_declarations():
    spec = ToolSpec("get_items", "Gets items.", {"type": "object", "properties": {"q": {"type": "string"}}})
    assert GeminiProvider.tool_declarations([spec]) == [{"functionDeclarations": [
        {"name": "get_items", "description": "Gets items.", "parametersJsonSchema": spec.parameters}]}]


def test_gemini_parses_parallel_function_calls_and_keeps_opaque_parts():
    data = {"candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": [
        {"thought": True, "text": "thinking", "thoughtSignature": "sig-A"},
        {"functionCall": {"name": "a", "args": {"x": 1}, "id": "fc-1"}, "thoughtSignature": "sig-B"},
        {"functionCall": {"name": "b", "args": {}}},
    ]}}], "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2, "totalTokenCount": 5}}
    r = GeminiProvider.parse_chat_response(data, "m")
    assert [(c.id, c.name, c.args, c.provider_id) for c in r.tool_calls] == [
        ("fc-1", "a", {"x": 1}, "fc-1"), ("call_2", "b", {}, None)]
    assert r.text == "" and r.usage.total_tokens == 5

    # The next request sends the model turn back exactly, signatures included,
    # then the responses in one user turn, matched by id where there was one.
    req = ChatRequest(model="m", api_key="k", tools=[], messages=[
        ChatMessage(role="user", text="go"),
        ChatMessage(role="model", raw=r.raw, tool_calls=r.tool_calls),
        ChatMessage(role="tool", tool_results=[
            {"id": "fc-1", "provider_id": "fc-1", "name": "a", "response": {"result": 1}},
            {"id": "call_2", "provider_id": None, "name": "b", "response": {"error": "no"}}]),
    ])
    contents = GeminiProvider().build_chat_body(req)["contents"]
    assert contents[1] == data["candidates"][0]["content"]
    assert contents[2] == {"role": "user", "parts": [
        {"functionResponse": {"name": "a", "response": {"result": 1}, "id": "fc-1"}},
        {"functionResponse": {"name": "b", "response": {"error": "no"}}}]}


def test_gemini_malformed_function_call_is_retryable_class():
    from app.llm.base import MalformedResponse

    with pytest.raises(MalformedResponse):
        GeminiProvider.parse_chat_response({"candidates": [{"finishReason": "MALFORMED_FUNCTION_CALL"}]}, "m")


def test_unsupported_schema_keywords_are_found():
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"a": {"type": "string", "const": "x"}, "b": {"type": "array", "items": {"oneOf": []}}}}
    assert unsupported_keywords(schema) == ["additionalProperties", "properties.a.const", "properties.b.items.oneOf"]


def test_scripted_provider_is_off_without_the_flag():
    import importlib
    import os

    import app.llm

    assert os.environ.get("ENABLE_TEST_PROVIDERS") != "1"
    assert "scripted" not in importlib.reload(app.llm).PROVIDERS


def test_scripted_provider_never_repeats_an_error_past_the_end():
    p = ScriptedProvider()
    req = lambda i: ChatRequest(model="s", api_key="", messages=[], tools=[], call_index=i,  # noqa: E731
                                options={"script": [{"text": "a"}, {"error": 503}]})
    assert p.chat(req(5)).text == "a"
    assert ToolCall  # imported for the adapter tests


def test_block_rejects_an_invalid_output_schema_and_tool_at_run_time():
    from blocks.agent import AgentBlock

    block = AgentBlock(providers={"scripted": ScriptedProvider()})
    base = {"provider": "scripted", "task": "t"}
    with pytest.raises(FatalError, match="not a valid JSON Schema"):
        block.settings({**base, "output_schema": {"type": "nope"}}, None)
    with pytest.raises(FatalError, match="parameters"):
        block.agent_tools({"tools": ["t1"]}, {"t1": http_tool_cfg(params={"type": "array"})})


async def test_exhausted_model_errors_keep_the_trace():
    with pytest.raises(RetryableError) as e:
        await make_run([{"tool_calls": [{"name": "get_items", "args": {}}]}, {"error": 503}]).run()
    assert e.value.detail["stop_reason"] == "error" and len(e.value.detail["trace"]) == 3
