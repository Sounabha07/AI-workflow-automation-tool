"""Shared helpers for the unit tests. Nothing here needs Postgres, Redis or
the network: these tests cover pure logic only."""

import pytest


def block(type_, next_=None, depends_on=None, config=None):
    """One block in the A2 definition shape."""
    return {
        "type": type_,
        "config": config or {},
        "depends_on": depends_on or [],
        "next": [] if next_ is None else next_,
        "position": {"x": 0, "y": 0},
        "notes": "",
    }


@pytest.fixture
def linear_definition():
    """trigger -> fetch -> notify"""
    return {"blocks": {
        "trigger": block("manual_trigger", ["fetch"]),
        "fetch": block("http_request", ["notify"], ["trigger"], {"url": "http://x"}),
        "notify": block("http_request", [], ["fetch"], {"url": "http://y"}),
    }}


@pytest.fixture
def switch_definition():
    """trigger -> route(switch) -> big / fallback"""
    return {"blocks": {
        "trigger": block("manual_trigger", ["route"]),
        "route": block(
            "switch",
            {"big": ["big_call"], "fallback": ["fallback_call"]},
            ["trigger"],
            {"value": "50", "rules": [{"operator": "greater_than", "compare_value": "10", "output": "big"}], "fallback": True},
        ),
        "big_call": block("http_request", [], ["route"], {"url": "http://x"}),
        "fallback_call": block("http_request", [], ["route"], {"url": "http://y"}),
    }}
