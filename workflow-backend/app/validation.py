"""
Structural validation for a workflow definition (the contract in PROMPT.md A2).
Returns human readable problems; an empty list means the definition is valid.
"""

import re
from typing import Any
from uuid import UUID

import blocks  # noqa: F401 -- importing this registers every block
from app.agent import tools as agent_tools
from app.llm import DEFAULT_PROVIDER, PROVIDERS
from blocks import TRIGGER_TYPES, WAIT_TYPE
from blocks.llm import RESPONSE_FORMATS, TEMPERATURE_RANGE
from blocks.registry import get_block_class, list_registered_types
from blocks.schedule_trigger import DEFAULT_TIMEZONE, schedule_problem
from blocks.switch import FALLBACK, switch_outputs
from blocks.wait_for_input import timeout_problem
from engine.resolver import PLACEHOLDER, RESUME_NAMESPACE, parse_json_template

BLOCK_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
RESERVED_BLOCK_IDS = {RESUME_NAMESPACE}
RESUME_FIELDS = ("token", "url")


def edge_targets(block_def: dict) -> list[str]:
    """Every target of a block's outgoing edges, flattening switch outputs."""
    nxt = block_def.get("next", [])
    if isinstance(nxt, dict):
        return [t for targets in nxt.values() if isinstance(targets, list) for t in targets]
    return list(nxt) if isinstance(nxt, list) else []


def config_of(block_def: Any) -> dict:
    """A block's config, or {} when it's missing or not an object (that
    case is reported once, by validate_definition)."""
    config = block_def.get("config") if isinstance(block_def, dict) else None
    return config if isinstance(config, dict) else {}


def _strings(value: Any):
    """Every string nested anywhere in a config value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _resume_ref_problems(block_defs: dict) -> list[str]:
    """{{ resume.<id>.token|url }} must name an existing wait block. These
    refs never create edges, so they play no part in the cycle check."""
    wait_ids = {bid for bid, b in block_defs.items() if isinstance(b, dict) and b.get("type") == WAIT_TYPE}
    problems: list[str] = []
    for block_id, b in block_defs.items():
        if not isinstance(b, dict):
            continue
        for text in _strings(config_of(b)):
            for m in PLACEHOLDER.finditer(text):
                segments = m.group(1).strip().split(".")
                if segments[0] != RESUME_NAMESPACE:
                    continue
                ref = "{{ " + m.group(1).strip() + " }}"
                if len(segments) < 2 or segments[1] not in wait_ids:
                    target = segments[1] if len(segments) > 1 else ""
                    problems.append(
                        f"Block '{block_id}': {ref} doesn't name a Wait for Input block"
                        + (f" ('{target}' isn't one)." if target else ".")
                    )
                elif len(segments) != 3 or segments[2] not in RESUME_FIELDS:
                    problems.append(
                        f"Block '{block_id}': {ref} must end in .token or .url."
                    )
    return problems


def validate_definition(definition: Any) -> list[str]:
    if not isinstance(definition, dict):
        return ["The definition must be an object with a 'blocks' key."]
    block_defs = definition.get("blocks")
    if not isinstance(block_defs, dict) or not block_defs:
        return ["The workflow needs at least one block."]

    problems: list[str] = []
    registered = set(list_registered_types())
    malformed: set[str] = set()

    for block_id, b in block_defs.items():
        if not isinstance(block_id, str) or not BLOCK_ID_PATTERN.match(block_id):
            problems.append(
                f"Block id '{block_id}' is invalid. Use lowercase letters, digits and "
                f"underscores, starting with a letter (max 63 characters)."
            )
        elif block_id in RESERVED_BLOCK_IDS:
            problems.append(f"Block id '{block_id}' is reserved. Pick another name.")
        if not isinstance(b, dict):
            problems.append(f"Block '{block_id}' must be an object.")
            malformed.add(block_id)
            continue

        block_type = b.get("type")
        if not isinstance(block_type, str) or block_type not in registered:
            problems.append(f"Block '{block_id}' has unknown type '{block_type}'.")
            block_type = None

        if b.get("config") is not None and not isinstance(b.get("config"), dict):
            problems.append(f"Block '{block_id}': 'config' must be an object.")
        config = config_of(b)

        depends_on = b.get("depends_on", [])
        if not isinstance(depends_on, list):
            problems.append(f"Block '{block_id}': 'depends_on' must be a list.")
            malformed.add(block_id)

        nxt = b.get("next", [])
        if block_type == "switch":
            if not isinstance(nxt, dict):
                problems.append(
                    f"Switch '{block_id}': 'next' must be an object keyed by output name."
                )
                malformed.add(block_id)
            else:
                rules = config.get("rules")
                rule_outputs = [
                    str(r.get("output", "")).strip()
                    for r in (rules if isinstance(rules, list) else []) if isinstance(r, dict)
                ]
                if any(not o for o in rule_outputs):
                    problems.append(f"Switch '{block_id}': every rule needs an output name.")
                if FALLBACK in rule_outputs:
                    problems.append(
                        f"Switch '{block_id}': 'fallback' is reserved and can't be a rule output."
                    )
                dupes = sorted({o for o in rule_outputs if o and rule_outputs.count(o) > 1})
                if dupes:
                    problems.append(
                        f"Switch '{block_id}': output names must be unique ({', '.join(dupes)})."
                    )
                outputs = set(switch_outputs(config))
                for key, targets in nxt.items():
                    if key not in outputs:
                        problems.append(
                            f"Switch '{block_id}' has edges on output '{key}', "
                            f"which is not one of its outputs."
                        )
                    if not isinstance(targets, list):
                        problems.append(
                            f"Switch '{block_id}': output '{key}' must map to a list of block ids."
                        )
                        malformed.add(block_id)
        elif not isinstance(nxt, list):
            problems.append(f"Block '{block_id}': 'next' must be a list.")
            malformed.add(block_id)

        if block_type == "llm":
            problems.extend(llm_config_problems(block_id, config))
        if block_type == agent_tools.AGENT_TYPE:
            problems.extend(agent_config_problems(block_id, config))

        if block_type in TRIGGER_TYPES and depends_on:
            problems.append(f"Trigger '{block_id}' can't have incoming connections.")

        if block_type == "schedule_trigger":
            problem = schedule_problem(config.get("cron"), config.get("timezone") or DEFAULT_TIMEZONE)
            if problem:
                problems.append(f"Schedule '{block_id}': {problem}")
        if block_type == WAIT_TYPE:
            timeout = config.get("timeout_seconds")
            # An expression is checked when it resolves, at run time.
            if not (isinstance(timeout, str) and "{{" in timeout):
                problem = timeout_problem(timeout)
                if problem:
                    problems.append(f"Wait '{block_id}': {problem}")

    triggers = sorted(
        bid for bid, b in block_defs.items() if isinstance(b, dict) and b.get("type") in TRIGGER_TYPES
    )
    if not triggers:
        problems.append("The workflow needs a trigger block (manual, schedule or webhook).")
    elif len(triggers) > 1:
        problems.append(
            f"A workflow can have only one trigger, but it has {len(triggers)}: {', '.join(triggers)}."
        )

    problems.extend(_resume_ref_problems(block_defs))
    problems.extend(tool_wiring_problems(block_defs))

    if malformed:
        return problems

    # Edges: existence, self-loops, duplicates, symmetry.
    edges: set[tuple[str, str]] = set()
    self_loops: set[str] = set()
    for a, b in block_defs.items():
        seen_targets: set[str] = set()
        for t in edge_targets(b):
            if t == a:
                if a not in self_loops:
                    problems.append(f"Block '{a}' can't connect to itself.")
                    self_loops.add(a)
                continue
            if t not in block_defs:
                problems.append(f"Block '{a}' connects to '{t}', which doesn't exist.")
                continue
            if t in seen_targets:
                problems.append(f"Blocks '{a}' and '{t}' are connected more than once.")
                continue
            seen_targets.add(t)
            edges.add((a, t))
            if a not in block_defs[t].get("depends_on", []):
                problems.append(
                    f"Block '{a}' connects to '{t}', but '{t}' doesn't list '{a}' in depends_on."
                )

    for b_id, b in block_defs.items():
        seen_deps: set[str] = set()
        for a in b.get("depends_on", []):
            if a == b_id:
                if a not in self_loops:
                    problems.append(f"Block '{a}' can't connect to itself.")
                    self_loops.add(a)
                continue
            if a not in block_defs:
                problems.append(f"Block '{b_id}' depends on '{a}', which doesn't exist.")
                continue
            if a in seen_deps:
                problems.append(f"Block '{b_id}' lists '{a}' in depends_on more than once.")
                continue
            seen_deps.add(a)
            if (a, b_id) not in edges:
                problems.append(
                    f"Block '{b_id}' depends on '{a}', but '{a}' doesn't list '{b_id}' in next."
                )

    # Cycles: iterative DFS over the valid edges.
    adjacency: dict[str, list[str]] = {bid: [] for bid in block_defs}
    for a, t in edges:
        adjacency[a].append(t)
    WHITE, GREY, BLACK = 0, 1, 2
    color = {bid: WHITE for bid in block_defs}
    for root in block_defs:
        if color[root] != WHITE:
            continue
        stack = [(root, iter(adjacency[root]))]
        color[root] = GREY
        path = [root]
        while stack:
            node, it = stack[-1]
            nxt_node = next(it, None)
            if nxt_node is None:
                color[node] = BLACK
                stack.pop()
                path.pop()
            elif color[nxt_node] == GREY:
                cycle = path[path.index(nxt_node):] + [nxt_node]
                problems.append(f"The workflow has a loop: {' -> '.join(cycle)}.")
                return problems
            elif color[nxt_node] == WHITE:
                color[nxt_node] = GREY
                stack.append((nxt_node, iter(adjacency[nxt_node])))
                path.append(nxt_node)

    return problems


def _is_template(value: Any) -> bool:
    return isinstance(value, str) and "{{" in value


def llm_config_problems(block_id: str, config: Any) -> list[str]:
    """Config checks for an llm block. Values that are {{ }} expressions are
    only known at run time, so the block re-checks them when it runs."""
    if not isinstance(config, dict):
        return [f"LLM '{block_id}': 'config' must be an object."]
    problems: list[str] = []

    provider = config.get("provider", DEFAULT_PROVIDER)
    if provider not in PROVIDERS:
        problems.append(
            f"LLM '{block_id}': unknown provider '{provider}'. Use one of: {', '.join(PROVIDERS)}."
        )

    if "api_key" in config:
        problems.append(
            f"LLM '{block_id}': API keys can't be stored in a workflow. "
            f"Save the key as a credential and select it instead."
        )
    credential = config.get("credential")
    if credential not in (None, ""):
        try:
            UUID(str(credential))
        except ValueError:
            problems.append(f"LLM '{block_id}': 'credential' must be a saved credential's id.")

    prompt = config.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        problems.append(f"LLM '{block_id}': the prompt can't be empty.")

    temperature = config.get("temperature")
    if temperature not in (None, "") and not _is_template(temperature):
        lo, hi = TEMPERATURE_RANGE
        try:
            t = float(temperature)
            if isinstance(temperature, bool) or not lo <= t <= hi:
                raise ValueError
        except (TypeError, ValueError):
            problems.append(f"LLM '{block_id}': temperature must be a number from {lo:g} to {hi:g}.")

    max_tokens = config.get("max_output_tokens")
    if max_tokens not in (None, "") and not _is_template(max_tokens):
        try:
            n = float(max_tokens)
            if isinstance(max_tokens, bool) or n != int(n) or n < 1:
                raise ValueError
        except (TypeError, ValueError):
            problems.append(f"LLM '{block_id}': max output tokens must be a positive whole number.")

    response_format = config.get("response_format", "text")
    if response_format not in RESPONSE_FORMATS:
        problems.append(f"LLM '{block_id}': response format must be 'text' or 'json'.")

    schema = config.get("json_schema")
    if schema not in (None, "", {}):
        if response_format != "json":
            problems.append(
                f"LLM '{block_id}': a JSON schema is only used when the response format is 'json'."
            )
        parsed = schema
        if isinstance(schema, str):
            try:
                parsed = parse_json_template(schema)
            except ValueError:
                parsed = None
        if not isinstance(parsed, dict):
            problems.append(f"LLM '{block_id}': the JSON schema must be a JSON object.")

    return problems


def _check_number(problems, label, value, lo, hi, integer=True):
    if value in (None, "") or _is_template(value):
        return
    try:
        n = float(value)
        if isinstance(value, bool) or (integer and n != int(n)) or not lo <= n <= hi:
            raise ValueError
    except (TypeError, ValueError):
        kind = "a whole number" if integer else "a number"
        problems.append(f"{label} must be {kind} from {lo:g} to {hi:g}.")


def _json_value(value: Any) -> Any:
    if isinstance(value, str) and value.strip():
        try:
            return parse_json_template(value)
        except ValueError:
            return None
    return value


def agent_config_problems(block_id: str, config: Any) -> list[str]:
    """Config checks for an agent block. Its tools are checked by
    tool_wiring_problems."""
    from blocks.agent import LIMITS

    if not isinstance(config, dict):
        return [f"Agent '{block_id}': 'config' must be an object."]
    problems: list[str] = []
    where = f"Agent '{block_id}'"
    provider = config.get("provider", DEFAULT_PROVIDER)
    if provider not in PROVIDERS:
        problems.append(f"{where}: unknown provider '{provider}'. Use one of: {', '.join(PROVIDERS)}.")
    if "api_key" in config:
        problems.append(f"{where}: API keys can't be stored in a workflow. Save the key as a credential instead.")
    credential = config.get("credential")
    if credential not in (None, ""):
        try:
            UUID(str(credential))
        except ValueError:
            problems.append(f"{where}: 'credential' must be a saved credential's id.")
    task = config.get("task")
    if not isinstance(task, str) or not task.strip():
        problems.append(f"{where}: the task can't be empty.")
    tools = config.get("tools", [])
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        problems.append(f"{where}: 'tools' must be a list of block ids.")
    schema = config.get("output_schema")
    if schema not in (None, "", {}):
        parsed = _json_value(schema)
        if not isinstance(parsed, dict):
            problems.append(f"{where}: the output schema must be a JSON object.")
        else:
            from jsonschema import Draft202012Validator
            from jsonschema.exceptions import SchemaError

            try:
                Draft202012Validator.check_schema(parsed)
            except SchemaError as e:
                problems.append(f"{where}: the output schema is not a valid JSON Schema: {e.message}")
    for name, (_, lo, hi) in LIMITS.items():
        _check_number(problems, f"{where}: {name}", config.get(name), lo, hi)
    _check_number(problems, f"{where}: max_total_tokens", config.get("max_total_tokens"), 1, 10**9)
    _check_number(problems, f"{where}: temperature", config.get("temperature"), *TEMPERATURE_RANGE, integer=False)
    return problems


def _refs(config: Any) -> set[str]:
    """Block ids a config's {{ }} expressions read from (resume links aside)."""
    found = set()
    for text in _strings(config or {}):
        for m in PLACEHOLDER.finditer(text):
            head = m.group(1).strip().split(".")[0]
            if head and head != RESUME_NAMESPACE:
                found.add(head)
    return found


def tool_wiring_problems(block_defs: dict) -> list[str]:
    """Blocks in an agent's tools aren't DAG nodes: no edges, exactly one
    agent, a complete tool definition, and every block their config
    references must be upstream of the agent (they resolve when it runs)."""
    problems: list[str] = []
    definition = {"blocks": block_defs}
    owners = agent_tools.tool_owners(definition)
    in_edges = {t for b in block_defs.values() if isinstance(b, dict) for t in edge_targets(b)}
    in_deps = {
        d for b in block_defs.values() if isinstance(b, dict) and isinstance(b.get("depends_on"), list)
        for d in b["depends_on"]
    }

    for tool_id, agents in sorted(owners.items()):
        first = agents[0]
        tool = block_defs.get(tool_id)
        if not isinstance(tool, dict):
            problems.append(f"Agent '{first}' lists tool '{tool_id}', which doesn't exist.")
            continue
        tool_type = tool.get("type")
        if tool_type == agent_tools.AGENT_TYPE:
            problems.append(f"Agent '{first}': '{tool_id}' is an agent, and agents can't use agents as tools.")
            continue
        try:
            usable = getattr(get_block_class(tool_type), "usable_as_tool", False)
        except KeyError:
            usable = False
        if not usable:
            problems.append(
                f"Agent '{first}': '{tool_id}' is a {tool_type} block; only HTTP Request blocks can be tools."
            )
            continue
        if len(set(agents)) > 1:
            problems.append(
                f"Tool '{tool_id}' is connected to more than one agent ({', '.join(sorted(set(agents)))})."
            )
        elif len(agents) > 1:
            problems.append(f"Agent '{first}' lists tool '{tool_id}' more than once.")
        if tool.get("depends_on") or tool.get("next"):
            problems.append(
                f"Tool '{tool_id}' can't have other connections: a tool runs only when its agent calls it."
            )
        if tool_id in in_edges or tool_id in in_deps:
            problems.append(f"Tool '{tool_id}' can't be connected into the workflow: only its agent uses it.")
        problems.extend(agent_tools.definition_problems(tool_id, config_of(tool)))

        upstream = ancestors(definition, first)
        for ref in sorted(_refs(config_of(tool))):
            if ref == tool_id or ref not in block_defs:
                continue
            if ref not in upstream:
                problems.append(
                    f"Tool '{tool_id}' uses '{ref}', which isn't upstream of its agent '{first}'. "
                    f"Connect '{ref}' before '{first}'."
                )

    for agent_id, b in block_defs.items():
        if not isinstance(b, dict) or b.get("type") != agent_tools.AGENT_TYPE:
            continue
        names: dict[str, set[str]] = {}
        for tool_id in agent_tools.agent_tool_ids(b):
            tool = block_defs.get(tool_id)
            if isinstance(tool, dict):
                name = str(config_of(tool).get("tool_name") or "").strip()
                if name:
                    names.setdefault(name, set()).add(tool_id)
        for name, ids in sorted(names.items()):
            if len(ids) > 1:
                problems.append(
                    f"Agent '{agent_id}': tool name '{name}' is used by {', '.join(sorted(ids))}. "
                    f"Tool names must be unique."
                )
    return problems


def definition_warnings(definition: Any) -> list[str]:
    """Things that are valid but may not do what the author expects."""
    if not isinstance(definition, dict) or not isinstance(definition.get("blocks"), dict):
        return []
    block_defs = definition["blocks"]
    warnings: list[str] = []
    for tool_id in sorted(agent_tools.tool_block_ids(definition)):
        tool = block_defs.get(tool_id)
        if not isinstance(tool, dict):
            continue
        keys = agent_tools.unsupported_keywords(agent_tools.tool_parameters(config_of(tool)))
        if keys:
            warnings.append(
                f"Tool '{tool_id}': Gemini may ignore these JSON Schema keywords in its parameters: "
                f"{', '.join(keys)}. Arguments are still checked against the full schema."
            )
    for block_id, b in block_defs.items():
        if isinstance(b, dict) and b.get("type") == agent_tools.AGENT_TYPE:
            schema = _json_value(config_of(b).get("output_schema"))
            keys = agent_tools.unsupported_keywords(schema) if isinstance(schema, dict) else []
            if keys:
                warnings.append(
                    f"Agent '{block_id}': Gemini may ignore these JSON Schema keywords in the output schema: "
                    f"{', '.join(keys)}. The final answer is still checked against the full schema."
                )
    return warnings


def ancestors(definition: dict, block_id: str) -> set[str]:
    """Every block upstream of block_id, following depends_on."""
    block_defs = definition.get("blocks", {})

    def deps(bid) -> list:
        b = block_defs.get(bid)
        d = b.get("depends_on", []) if isinstance(b, dict) else []
        return [x for x in d if isinstance(x, str)] if isinstance(d, list) else []

    found: set[str] = set()
    stack = deps(block_id)
    while stack:
        a = stack.pop()
        if a in found or a not in block_defs:
            continue
        found.add(a)
        stack.extend(deps(a))
    return found


class InvalidWorkflowError(Exception):
    """Rendered by app.main as 400 {"detail": "Invalid workflow", "problems": [...]}."""

    def __init__(self, problems: list[str]):
        super().__init__("Invalid workflow")
        self.problems = problems


def ensure_valid(definition: Any) -> None:
    problems = validate_definition(definition)
    if problems:
        raise InvalidWorkflowError(problems)
