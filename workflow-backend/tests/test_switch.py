import pytest

from blocks.base import FatalError
from blocks.switch import SwitchBlock, switch_outputs


def rule(operator, compare_value, output):
    return {"operator": operator, "compare_value": compare_value, "output": output}


async def route(value, rules, fallback=True):
    return await SwitchBlock().execute({"value": value, "rules": rules, "fallback": fallback}, input_data={})


async def test_first_matching_rule_wins():
    out = await route(50, [rule("greater_than", "10", "big"), rule("greater_than", "1", "any")])
    assert out == {"branch_taken": "big", "value": 50}


async def test_no_match_goes_to_fallback_or_nowhere():
    assert (await route(5, [rule("greater_than", "10", "big")]))["branch_taken"] == "fallback"
    assert (await route(5, [rule("greater_than", "10", "big")], fallback=False))["branch_taken"] is None


@pytest.mark.parametrize("value,operator,compare,expected", [
    ("50", "equals", "50.0", True),     # numeric comparison when both parse
    ("abc", "equals", "abc", True),     # string comparison otherwise
    ("abc", "not_equals", "abd", True),
    ("hello world", "contains", "wor", True),
    ("3", "less_than", "10", True),     # 3 < 10 numerically, not "3" > "10" as strings
    ("", "is_empty", "", True),
    ([], "is_empty", "", True),
    ("x", "is_empty", "", False),
])
async def test_operators(value, operator, compare, expected):
    out = await route(value, [rule(operator, compare, "hit")], fallback=True)
    assert (out["branch_taken"] == "hit") is expected


async def test_numeric_operator_on_non_number_is_fatal():
    with pytest.raises(FatalError, match="needs numbers"):
        await route("abc", [rule("greater_than", "10", "big")])


@pytest.mark.parametrize("rules,message", [
    ([rule("equals", "1", "")], "needs an output name"),
    ([rule("equals", "1", "fallback")], "reserved"),
    ([rule("equals", "1", "a"), rule("equals", "2", "a")], "more than once"),
])
async def test_bad_output_names_are_fatal(rules, message):
    with pytest.raises(FatalError, match=message):
        await route(1, rules)


def test_switch_outputs_lists_rules_then_fallback():
    cfg = {"rules": [rule("equals", "1", "a"), rule("equals", "2", "b")], "fallback": True}
    assert switch_outputs(cfg) == ["a", "b", "fallback"]
    assert switch_outputs({**cfg, "fallback": False}) == ["a", "b"]
