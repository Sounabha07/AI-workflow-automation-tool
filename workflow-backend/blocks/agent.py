"""
Agent Block — a model that can call tools in a loop until it has an answer.

Tools are http_request blocks connected to the agent's Tools port (their ids
in config.tools). They are not DAG nodes; the agent calls them. All the
machinery is in app/agent/; this is the block-contract wrapper.

Output:
    {"final", "text", "trace", "iterations", "tool_calls", "stop_reason",
     "usage": {input_tokens, output_tokens, total_tokens}}
`final` is the validated structured answer when output_schema is set, else
the final text. Downstream: {{ agent_1.final.some_field }}.

Errors:
- model errors: classified like the LLM block (429/5xx/timeouts retry, and
  a retry resumes from the checkpoint without repeating tool calls)
- max_iterations, max_total_tokens, timeout: non-retryable, with
  {stop_reason, trace, usage} in the error detail
- a failing tool call is never a block failure: the model sees the error
"""

import json
from typing import Any

import events
from app.agent.tools import side_effects, tool_spec
from app.llm import DEFAULT_PROVIDER, PROVIDER_LABELS, PROVIDERS
from blocks.base import BaseBlock, FatalError
from blocks.llm import LLMBlock, TEMPERATURE_RANGE, _number, resolve_api_key
from blocks.registry import register_block

_DEFAULT_PROVIDER = PROVIDERS[DEFAULT_PROVIDER]

LIMITS = {
    # name: (default, min, max)
    "max_iterations": (10, 1, 50),
    "timeout_seconds": (300, 1, 3600),
    "tool_timeout_seconds": (30, 1, 600),
    "max_tool_result_chars": (4000, 100, 100_000),
}

AGENT_BLOCK_SCHEMA = {
    "name": "AI Agent",
    "category": "ai",
    "description": "A model that calls your HTTP tools in a loop until it has an answer",
    "icon": "agent",
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
            "type": "options",
            "required": True,
            "default": _DEFAULT_PROVIDER.default_model,
            "options": _DEFAULT_PROVIDER.models,
        },
        {
            "name": "credential",
            "label": "Credential",
            "type": "credential",
            "credential_types": [p.credential_type for p in PROVIDERS.values() if p.credential_type],
            "placeholder": f"None: use the server's {_DEFAULT_PROVIDER.env_var}",
            "description": "Your own saved API key. With none selected, the server's key is used if one is set.",
        },
        {
            "name": "task",
            "label": "Task",
            "type": "text",
            "required": True,
            "placeholder": "Find the most recent failed workflow and explain the error. {{ input_1.values.q }}",
        },
        {
            "name": "system_prompt",
            "label": "System prompt",
            "type": "text",
            "placeholder": "You are a careful operations assistant.",
        },
        {
            "name": "tools",
            "label": "Tools",
            "type": "tool_list",
            "default": [],
            "description": "Connect HTTP Request blocks to the agent's Tools handle.",
        },
        {
            "name": "output_schema",
            "label": "Output schema",
            "type": "json",
            "placeholder": '{"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}',
            "description": "Optional. The agent must finish with an object matching this JSON Schema.",
        },
        {"name": "temperature", "label": "Temperature", "type": "number", "placeholder": "Model default",
         "description": "0 to 2."},
        {"name": "max_iterations", "label": "Max iterations", "type": "number", "default": 10,
         "description": "Model turns, 1 to 50."},
        {"name": "max_total_tokens", "label": "Max total tokens", "type": "number", "placeholder": "No limit",
         "description": "Summed over every model call."},
        {"name": "timeout_seconds", "label": "Timeout (seconds)", "type": "number", "default": 300,
         "description": "Total time, counted from the first attempt."},
        {"name": "tool_timeout_seconds", "label": "Tool timeout (seconds)", "type": "number", "default": 30},
        {"name": "max_tool_result_chars", "label": "Max tool result characters", "type": "number",
         "default": 4000, "description": "Longer results are cut before the model sees them."},
        {
            "name": "script",
            "label": "Script (test provider)",
            "type": "json",
            "show_when": {"provider": "scripted"},
            "description": "Responses the scripted provider replays, in order.",
        },
    ],
}


def _load_json(value: Any, name: str) -> Any:
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            raise FatalError(f"Agent block: '{name}' is not valid JSON: {e}") from None
    return value


def limit(config: dict, name: str) -> int:
    default, lo, hi = LIMITS[name]
    value = _number(config.get(name, default), name, integer=True)
    value = default if value is None else value
    if not lo <= value <= hi:
        raise FatalError(f"Agent block: '{name}' must be from {lo} to {hi}, got {value}.")
    return value


@register_block("agent")
class AgentBlock(BaseBlock):
    schema = AGENT_BLOCK_SCHEMA
    usable_as_tool = False

    max_retries: int = 3
    retry_backoff_base_seconds: float = 2.0
    retry_backoff_cap_seconds: float = 60.0

    def __init__(self, providers: dict | None = None, store=None, executor=None):
        self._providers = providers
        self._store = store
        self._executor = executor

    def _provider(self, name: str):
        if self._providers is not None and name in self._providers:
            return self._providers[name]
        if name not in PROVIDERS:
            raise FatalError(f"Agent block: unknown provider '{name}'. Available: {', '.join(PROVIDERS)}.")
        return PROVIDERS[name]()

    def settings(self, config: dict, credentials: dict | None):
        # app.agent.loop imports blocks.base, which imports this module.
        from app.agent.loop import AgentSettings

        provider_name = str(config.get("provider") or DEFAULT_PROVIDER)
        provider = self._provider(provider_name)
        task = config.get("task")
        if not isinstance(task, str):
            task = "" if task is None else json.dumps(task, ensure_ascii=False, default=str)
        if not task.strip():
            raise FatalError("Agent block: 'task' is required but was empty.")
        system_prompt = config.get("system_prompt")
        if system_prompt is not None and not isinstance(system_prompt, str):
            system_prompt = json.dumps(system_prompt, ensure_ascii=False, default=str)

        temperature = _number(config.get("temperature"), "temperature")
        if temperature is not None and not TEMPERATURE_RANGE[0] <= temperature <= TEMPERATURE_RANGE[1]:
            raise FatalError(f"Agent block: 'temperature' must be between 0 and 2, got {temperature:g}.")
        output_schema = _load_json(config.get("output_schema"), "output_schema") or None
        if output_schema is not None and not isinstance(output_schema, dict):
            raise FatalError("Agent block: 'output_schema' must be a JSON object.")
        script = _load_json(config.get("script"), "script")

        return AgentSettings(
            provider=provider,
            provider_name=provider_name,
            model=str(config.get("model") or "").strip() or provider.default_model,
            api_key=resolve_api_key(provider, provider_name, credentials, "Agent block"),
            task=task,
            system_prompt=system_prompt or None,
            temperature=temperature,
            output_schema=output_schema,
            max_iterations=limit(config, "max_iterations"),
            max_total_tokens=_number(config.get("max_total_tokens"), "max_total_tokens", integer=True),
            timeout_seconds=limit(config, "timeout_seconds"),
            tool_timeout_seconds=limit(config, "tool_timeout_seconds"),
            max_tool_result_chars=limit(config, "max_tool_result_chars"),
            options={"script": script} if script is not None else {},
        )

    @staticmethod
    def agent_tools(config: dict, tool_configs: dict) -> list:
        from app.agent.loop import AgentTool

        tools = []
        for tool_id in config.get("tools") or []:
            tc = tool_configs.get(tool_id)
            if tc is None:
                raise FatalError(f"Agent block: tool block '{tool_id}' isn't in this workflow.")
            tools.append(AgentTool(tool_id, tool_spec(tc), tc, side_effects(tc)))
        return tools

    async def execute(
        self,
        config: dict[str, Any],
        input_data: dict[str, Any],
        credentials: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.agent.loop import AgentRun
        from app.agent.steps import PostgresStepStore

        settings = self.settings(config, credentials)
        tools = self.agent_tools(config, input_data.get("tools") or {})
        run_id = str(config.get("run_id") or "")
        block_id = str(config.get("block_id") or "")

        def on_step(step: dict) -> None:
            events.publish(run_id, {"type": "agent.step", "block_id": block_id, **step})

        where = f"Agent block ({settings.provider_name}, model '{settings.model}')"

        def classify(e):
            err = LLMBlock._classify(e, settings.provider_name, settings.model)
            err.args = (str(err).replace(f"LLM block ({settings.provider_name}, model '{settings.model}')", where),)
            return err

        run = AgentRun(
            settings, tools,
            store=self._store or PostgresStepStore(),
            run_id=run_id, block_id=block_id,
            started_at=input_data.get("started_at"),
            executor=self._executor,
            on_step=on_step,
            classify=classify,
        )
        return await run.run()
