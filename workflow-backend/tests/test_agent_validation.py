"""Validation of agent blocks and their tool wiring, and how the engine
treats tool blocks (not DAG nodes)."""

import json

import engine
from app.validation import definition_warnings, validate_definition
from tests.conftest import block
from tests.fakes import ScriptedConn


def tool(name="get_x", **cfg):
    return block("http_request", config={
        "method": "GET", "url": "http://api.test/x", "tool_name": name,
        "tool_description": "Gets x from the test API for the agent.",
        "tool_parameters": {"type": "object", "properties": {"q": {"type": "string"}}}, **cfg})


def agent_definition(**overrides):
    blocks = {
        "trigger": block("manual_trigger", ["agent_1"]),
        "agent_1": block("agent", [], ["trigger"], {"task": "do it", "tools": ["t1", "t2"]}),
        "t1": tool("get_x"),
        "t2": tool("get_y"),
    }
    blocks.update(overrides)
    return {"blocks": blocks}


def problems(definition):
    return " | ".join(validate_definition(definition))


def test_valid_agent_definition():
    assert validate_definition(agent_definition()) == []


def test_agent_config_problems():
    d = agent_definition(agent_1=block("agent", [], ["trigger"], {
        "task": "", "tools": ["t1", "t2"], "output_schema": "[1]", "max_iterations": 51, "temperature": 3}))
    p = problems(d)
    for needle in ("task can't be empty", "output schema must be a JSON object",
                   "max_iterations must be a whole number from 1 to 50", "temperature must be a number"):
        assert needle in p


def test_tool_definition_problems():
    d = agent_definition(t1=tool("finish"), t2=tool("bad name!", tool_description="short",
                                                    tool_parameters={"type": "array"}))
    p = problems(d)
    for needle in ("reserved", "must be letters, digits and underscores", "at least 20 characters",
                   'must have "type": "object"'):
        assert needle in p


def test_tool_names_unique_per_agent():
    assert "Tool names must be unique" in problems(agent_definition(t2=tool("get_x")))


def test_tools_must_be_http_blocks_and_never_agents():
    d = agent_definition()
    d["blocks"]["agent_1"]["config"]["tools"] = ["t1", "trigger", "agent_2"]
    d["blocks"]["agent_2"] = block("agent", [], ["trigger"], {"task": "x", "tools": []})
    d["blocks"]["trigger"]["next"].append("agent_2")
    p = problems(d)
    assert "only HTTP Request blocks can be tools" in p and "agents can't use agents as tools" in p


def test_a_tool_belongs_to_one_agent_and_has_no_edges():
    d = agent_definition()
    d["blocks"]["agent_2"] = block("agent", [], ["trigger"], {"task": "x", "tools": ["t1"]})
    d["blocks"]["trigger"]["next"] += ["agent_2", "t2"]
    d["blocks"]["t2"]["depends_on"] = ["trigger"]
    p = problems(d)
    assert "more than one agent" in p and "can't have other connections" in p and "only its agent uses it" in p


def test_missing_tool_block():
    d = agent_definition()
    d["blocks"]["agent_1"]["config"]["tools"].append("ghost")
    assert "lists tool 'ghost', which doesn't exist" in problems(d)


def test_tool_references_count_as_the_agents():
    d = agent_definition(t1=tool(url="http://api.test/{{ trigger.body.repo }}"))
    assert validate_definition(d) == []  # trigger is upstream of agent_1
    d["blocks"]["later"] = block("http_request", [], ["agent_1"], {"url": "http://x"})
    d["blocks"]["agent_1"]["next"] = ["later"]
    d["blocks"]["t1"]["config"]["url"] = "http://api.test/{{ later.data.x }}"
    assert "isn't upstream of its agent 'agent_1'" in problems(d)


def test_gemini_unsupported_keywords_are_warnings():
    d = agent_definition(t1=tool(tool_parameters={"type": "object", "additionalProperties": False}))
    assert validate_definition(d) == []
    assert any("additionalProperties" in w for w in definition_warnings(d))


async def test_create_run_skips_tool_blocks():
    d = agent_definition()
    conn = ScriptedConn({
        "SELECT definition, is_active FROM pipelines": {"definition": json.dumps(d), "is_active": True},
        "INSERT INTO runs": "run-1",
    })
    run = await engine.create_run(conn, "p-1")
    insert_runs = next(args for q, args in conn.calls if "INSERT INTO runs" in q)
    assert insert_runs[4] == 2  # total_blocks: trigger and agent_1 only
    rows = [args[1] for q, args in conn.calls if "INSERT INTO block_executions" in q]
    assert rows == ["trigger", "agent_1"] and run.ready_block_ids == ["trigger"]
