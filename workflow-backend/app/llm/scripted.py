"""
Scripted provider: replays a fixed list of responses from the block config,
for CI and crash drills. Registered only when ENABLE_TEST_PROVIDERS=1 (see
app/llm/__init__.py), so production workflows can't select it.

The script is a list; model call N (counting failed calls, which the agent
records) gets item N, and the last item repeats once the list runs out:

    {"text": "the answer"}
    {"tool_calls": [{"name": "get_x", "args": {"q": 1}}, ...], "text": "optional"}
    {"finish": {"field": "value"}}        a call to the reserved finish tool
    {"error": 503}                        raises ProviderHTTPError(503)
    {"error": {"status": 429, "body": "slow down"}}
    any item may add "usage": {"input_tokens", "output_tokens", "total_tokens"}

Error items never repeat: past the end of the list, the last non-error
item is used, so "fail once, then carry on" scripts terminate.
"""

from app.llm.base import (
    ChatRequest,
    ChatResponse,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    MalformedResponse,
    ProviderHTTPError,
    ToolCall,
)

DEFAULT_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class ScriptedProvider:
    env_var = "SCRIPTED_PROVIDER_KEY"  # never read: no key is needed
    default_model = "scripted"
    models = [{"label": "Scripted (test)", "value": "scripted"}]
    credential_type = None
    credential_label = None
    needs_api_key = False

    @staticmethod
    def _item(script, index: int) -> dict:
        if not isinstance(script, list) or not script:
            raise MalformedResponse("scripted provider: the block's 'script' must be a non-empty list")
        if index < len(script):
            item = script[index]
        else:
            tail = [i for i in script if not (isinstance(i, dict) and "error" in i)]
            if not tail:
                raise MalformedResponse("scripted provider: the script ran out")
            item = tail[-1]
        if not isinstance(item, dict):
            raise MalformedResponse(f"scripted provider: item {index} is not an object")
        return item

    @staticmethod
    def _usage(item: dict) -> LLMUsage:
        u = {**DEFAULT_USAGE, **(item.get("usage") or {})}
        return LLMUsage(u.get("input_tokens"), u.get("output_tokens"), u.get("total_tokens"))

    @staticmethod
    def _raise(err) -> None:
        if isinstance(err, dict):
            status, body = int(err.get("status", 500)), str(err.get("body", "scripted error"))
        else:
            status, body = int(err), "scripted error"
        raise ProviderHTTPError(status, body)

    def chat(self, req: ChatRequest) -> ChatResponse:
        index = req.call_index
        item = self._item(req.options.get("script"), index)
        if "error" in item:
            self._raise(item["error"])

        calls: list[ToolCall] = []
        for i, c in enumerate(item.get("tool_calls") or []):
            calls.append(ToolCall(id=f"call_{i}", name=str(c.get("name", "")), args=dict(c.get("args") or {})))
        if "finish" in item:
            calls.append(ToolCall(id=f"call_{len(calls)}", name="finish", args=dict(item["finish"] or {})))
        text = str(item.get("text") or "")

        parts: list[dict] = [{"text": text}] if text else []
        parts += [{"functionCall": {"name": c.name, "args": c.args}} for c in calls]
        if parts:
            # Stands in for the opaque parts a real provider sends back.
            parts[0] = {**parts[0], "thoughtSignature": f"scripted-signature-{index}"}
        return ChatResponse(
            text=text,
            tool_calls=calls,
            raw={"role": "model", "parts": parts},
            finish_reason="stop",
            usage=self._usage(item),
            model="scripted",
        )

    def generate(self, req: LLMRequest) -> LLMResponse:
        # The llm block has no script field; answer with the prompt.
        return LLMResponse(text=req.prompt, finish_reason="stop", usage=LLMUsage(**DEFAULT_USAGE), model="scripted")
