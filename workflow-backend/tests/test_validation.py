import pytest

from app.validation import ancestors, validate_definition
from tests.conftest import block


def has_problem(problems, *fragments):
    return any(all(f in p for f in fragments) for p in problems)


def test_valid_linear_definition_has_no_problems(linear_definition):
    assert validate_definition(linear_definition) == []


def test_valid_switch_definition_has_no_problems(switch_definition):
    assert validate_definition(switch_definition) == []


def test_empty_or_missing_blocks_rejected():
    assert validate_definition({"blocks": {}}) == ["The workflow needs at least one block."]
    assert validate_definition({}) == ["The workflow needs at least one block."]
    assert validate_definition("nope") == ["The definition must be an object with a 'blocks' key."]


def test_invalid_block_id_and_unknown_type(linear_definition):
    linear_definition["blocks"]["Bad-Id"] = block("teleport")
    problems = validate_definition(linear_definition)
    assert has_problem(problems, "Bad-Id", "invalid")
    assert has_problem(problems, "unknown type 'teleport'")


def test_asymmetric_edges_are_reported(linear_definition):
    # fetch -> notify stays in `next`, but notify forgets it in depends_on.
    linear_definition["blocks"]["notify"]["depends_on"] = []
    problems = validate_definition(linear_definition)
    assert has_problem(problems, "'fetch' connects to 'notify'", "depends_on")


def test_edge_to_missing_block(linear_definition):
    linear_definition["blocks"]["notify"]["next"] = ["ghost"]
    assert has_problem(validate_definition(linear_definition), "'ghost', which doesn't exist")


def test_self_loop_reported_once(linear_definition):
    b = linear_definition["blocks"]["fetch"]
    b["next"].append("fetch")
    b["depends_on"].append("fetch")
    problems = validate_definition(linear_definition)
    assert sum("can't connect to itself" in p for p in problems) == 1


def test_cycle_detected():
    d = {"blocks": {
        "t": block("manual_trigger", ["a"]),
        "a": block("http_request", ["b"], ["t", "b"]),
        "b": block("http_request", ["a"], ["a"]),
    }}
    assert has_problem(validate_definition(d), "loop")


def test_trigger_cannot_have_incoming_edges():
    d = {"blocks": {
        "a": block("http_request", ["t"]),
        "t": block("manual_trigger", [], ["a"]),
    }}
    assert has_problem(validate_definition(d), "Trigger 't'", "incoming")


def test_switch_next_must_be_an_object(switch_definition):
    switch_definition["blocks"]["route"]["next"] = ["big_call"]
    assert has_problem(validate_definition(switch_definition), "Switch 'route'", "object keyed by output")


def test_switch_edges_must_hang_off_real_outputs(switch_definition):
    switch_definition["blocks"]["route"]["config"]["fallback"] = False
    assert has_problem(validate_definition(switch_definition), "output 'fallback'", "not one of its outputs")


def test_switch_rule_outputs_unique_nonempty_not_fallback(switch_definition):
    cfg = switch_definition["blocks"]["route"]["config"]
    cfg["rules"] = [
        {"operator": "equals", "compare_value": "1", "output": "dup"},
        {"operator": "equals", "compare_value": "2", "output": "dup"},
        {"operator": "equals", "compare_value": "3", "output": ""},
        {"operator": "equals", "compare_value": "4", "output": "fallback"},
    ]
    problems = validate_definition(switch_definition)
    assert has_problem(problems, "must be unique", "dup")
    assert has_problem(problems, "every rule needs an output name")
    assert has_problem(problems, "'fallback' is reserved")


def test_duplicate_edge_through_two_switch_outputs(switch_definition):
    route = switch_definition["blocks"]["route"]
    route["next"] = {"big": ["big_call"], "fallback": ["big_call"]}
    switch_definition["blocks"]["fallback_call"]["depends_on"] = []
    assert has_problem(validate_definition(switch_definition), "connected more than once")


def test_ancestors_follow_depends_on_transitively(linear_definition):
    assert ancestors(linear_definition, "notify") == {"fetch", "trigger"}
    assert ancestors(linear_definition, "fetch") == {"trigger"}
    assert ancestors(linear_definition, "trigger") == set()


def test_ancestors_with_fan_in(switch_definition):
    d = switch_definition
    d["blocks"]["join"] = block("http_request", [], ["big_call", "fallback_call"])
    d["blocks"]["big_call"]["next"] = ["join"]
    d["blocks"]["fallback_call"]["next"] = ["join"]
    assert ancestors(d, "join") == {"big_call", "fallback_call", "route", "trigger"}
    assert validate_definition(d) == []


# --- triggers, wait blocks, resume refs ---

def wait_definition(notify_url="http://x/?link={{ resume.wait.url }}"):
    """trigger -> notify -> wait -> after, where notify links to wait's resume URL."""
    return {"blocks": {
        "trigger": block("manual_trigger", ["notify"]),
        "notify": block("http_request", ["wait"], ["trigger"], {"url": notify_url}),
        "wait": block("wait_for_input", ["after"], ["notify"], {"timeout_seconds": 60}),
        "after": block("http_request", [], ["wait"], {"url": "http://y/{{ wait.data.x }}"}),
    }}


def test_resume_ref_upstream_of_its_wait_is_valid_and_not_a_cycle():
    assert validate_definition(wait_definition()) == []
    assert validate_definition(wait_definition("{{ resume.wait.token }}")) == []


@pytest.mark.parametrize("ref,fragment", [
    ("{{ resume.notify.url }}", "doesn't name a Wait for Input block ('notify'"),
    ("{{ resume.ghost.url }}", "('ghost' isn't one)"),
    ("{{ resume }}", "doesn't name a Wait for Input block."),
    ("{{ resume.wait }}", "must end in .token or .url"),
    ("{{ resume.wait.secret }}", "must end in .token or .url"),
])
def test_bad_resume_refs(ref, fragment):
    assert has_problem(validate_definition(wait_definition(f"http://x/{ref}")), "'notify'", fragment)


def test_resume_is_a_reserved_block_id():
    d = {"blocks": {
        "t": block("manual_trigger", ["resume"]),
        "resume": block("http_request", [], ["t"], {"url": "http://x"}),
    }}
    assert has_problem(validate_definition(d), "'resume' is reserved")


def test_exactly_one_trigger():
    assert has_problem(
        validate_definition({"blocks": {"a": block("http_request", config={"url": "http://x"})}}),
        "needs a trigger",
    )
    two = {"blocks": {
        "m": block("manual_trigger"),
        "h": block("webhook_trigger"),
    }}
    assert has_problem(validate_definition(two), "only one trigger", "h, m")


@pytest.mark.parametrize("trigger_type", ["schedule_trigger", "webhook_trigger"])
def test_every_trigger_type_is_a_root(trigger_type):
    config = {"cron": "* * * * *"} if trigger_type == "schedule_trigger" else {}
    d = {"blocks": {
        "a": block("http_request", ["t"], config={"url": "http://x"}),
        "t": block(trigger_type, [], ["a"], config),
    }}
    assert has_problem(validate_definition(d), "Trigger 't'", "incoming")


@pytest.mark.parametrize("config,fragment", [
    ({"cron": "every day"}, "exactly 5 fields"),
    ({"cron": "99 * * * *"}, "not a valid cron"),
    ({"cron": "0 9 * * *", "timezone": "Not/AZone"}, "Unknown timezone"),
    ({}, "cron expression is required"),
])
def test_bad_schedules(config, fragment):
    d = {"blocks": {"s": block("schedule_trigger", config=config)}}
    assert has_problem(validate_definition(d), "Schedule 's'", fragment)


def test_good_schedule_defaults_to_utc():
    assert validate_definition({"blocks": {"s": block("schedule_trigger", config={"cron": "0 9 * * 1-5"})}}) == []


@pytest.mark.parametrize("timeout", [0, 604801, None, "abc"])
def test_bad_wait_timeouts(timeout):
    d = wait_definition()
    d["blocks"]["wait"]["config"]["timeout_seconds"] = timeout
    assert has_problem(validate_definition(d), "Wait 'wait'", "timeout_seconds")


def test_wait_timeout_expression_is_checked_at_run_time():
    d = wait_definition()
    d["blocks"]["wait"]["config"]["timeout_seconds"] = "{{ notify.data.ttl }}"
    assert validate_definition(d) == []
