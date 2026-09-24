import json

import pytest

import engine.resolver as resolver
from blocks.http_request import HttpRequestBlock
from engine.resolver import parse_json_template, resolve, structure_json_fields

STATE = {"gh": {"data": {"full_name": "n8n-io/n8n", "stars": 205824, "archived": False, "owner": {"login": "n8n-io"}}}}


@pytest.mark.parametrize("text,expected", [
    ("{{ gh.data.stars }}", 205824),                # exactly one expression keeps its type
    ("  {{gh.data.stars}} ", 205824),              # surrounding whitespace is fine
    ("{{ gh.data.owner }}", {"login": "n8n-io"}),
    ("{{ gh.data.archived }}", False),
    ("Stars: {{ gh.data.stars }}", "Stars: 205824"),  # embedded -> string
    ("{{ gh.data.full_name }} {{ gh.data.stars }}", "n8n-io/n8n 205824"),  # two tokens, not one
    ("archived={{ gh.data.archived }}", "archived=false"),  # embedded non-strings use JSON
    ("no placeholders", "no placeholders"),
])
def test_resolve_string(text, expected):
    assert resolve(text, STATE) == expected


def test_resolve_walks_nested_config():
    cfg = {"url": "https://x/{{ gh.data.full_name }}", "pairs": [{"key": "n", "value": "{{ gh.data.stars }}"}], "n": 3}
    assert resolve(cfg, STATE) == {"url": "https://x/n8n-io/n8n", "pairs": [{"key": "n", "value": 205824}], "n": 3}


def test_unresolvable_reference_raises_readable_value_error():
    with pytest.raises(ValueError, match="block 'missing' has no output"):
        resolve("{{ missing.field }}", STATE)
    with pytest.raises(ValueError, match="path stopped at 'gh.data.nope'"):
        resolve("{{ gh.data.nope }}", STATE)


def test_json_template_quotes_bare_placeholders_and_keeps_types():
    tpl = '{"repo": "{{ gh.data.full_name }}", "stars": {{ gh.data.stars }}, "quoted": "{{ gh.data.stars }}", "label": "#{{ gh.data.stars }}"}'
    assert resolve(parse_json_template(tpl), STATE) == {
        "repo": "n8n-io/n8n", "stars": 205824, "quoted": 205824, "label": "#205824",
    }


def test_json_template_leaves_braces_inside_strings_alone():
    assert parse_json_template('{"a": "literal {{ not.a.token }} text", "b": "{\\"x\\": 1}"}') == {
        "a": "literal {{ not.a.token }} text", "b": '{"x": 1}',
    }


def test_invalid_json_template_raises():
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_json_template('{"a": }')
    with pytest.raises(ValueError, match="Unclosed"):
        parse_json_template('{"a": {{ gh.data.stars }')


def test_structure_json_fields_only_touches_json_typed_fields():
    cfg = {"body_json": '{"n": {{ gh.data.stars }}}', "url": '{"not": "a json field"}'}
    out = structure_json_fields(cfg, HttpRequestBlock.schema)
    assert out["body_json"] == {"n": "{{ gh.data.stars }}"}
    assert out["url"] == cfg["url"]


class FakeConn:
    """Stands in for an asyncpg connection in build_run_state."""

    def __init__(self, seed, rows):
        self.seed, self.rows, self.closed = seed, rows, False

    async def fetchval(self, query, *args):
        assert "seed_outputs" in query
        return self.seed

    async def fetch(self, query, *args):
        assert "block_executions" in query
        return self.rows

    async def close(self):
        self.closed = True


async def test_build_run_state_starts_from_seed_then_overlays_real_outputs(monkeypatch):
    conn = FakeConn(
        seed=json.dumps({"fetch": {"stale": True}, "earlier": {"kept": 1}}),
        rows=[{"block_id": "fetch", "output": json.dumps({"fresh": True})}, {"block_id": "new", "output": {"x": 2}}],
    )

    async def fake_get_connection():
        return conn

    monkeypatch.setattr(resolver, "get_connection", fake_get_connection)
    state = await resolver.build_run_state("run-1")
    assert state == {"fetch": {"fresh": True}, "earlier": {"kept": 1}, "new": {"x": 2}}
    assert conn.closed


async def test_build_run_state_without_seed(monkeypatch):
    conn = FakeConn(seed=None, rows=[{"block_id": "a", "output": {"v": 1}}])

    async def fake_get_connection():
        return conn

    monkeypatch.setattr(resolver, "get_connection", fake_get_connection)
    assert await resolver.build_run_state("run-2") == {"a": {"v": 1}}
