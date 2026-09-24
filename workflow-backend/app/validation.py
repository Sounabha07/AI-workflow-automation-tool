"""
Structural validation for a workflow definition (the contract in PROMPT.md A2).
Returns human readable problems; an empty list means the definition is valid.
"""

import re
from typing import Any

import blocks  # noqa: F401 -- importing this registers every block
from blocks.registry import list_registered_types
from blocks.switch import FALLBACK, switch_outputs

BLOCK_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def edge_targets(block_def: dict) -> list[str]:
    """Every target of a block's outgoing edges, flattening switch outputs."""
    nxt = block_def.get("next", [])
    if isinstance(nxt, dict):
        return [t for targets in nxt.values() if isinstance(targets, list) for t in targets]
    return list(nxt) if isinstance(nxt, list) else []


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
        if not BLOCK_ID_PATTERN.match(block_id):
            problems.append(
                f"Block id '{block_id}' is invalid. Use lowercase letters, digits and "
                f"underscores, starting with a letter (max 63 characters)."
            )
        if not isinstance(b, dict):
            problems.append(f"Block '{block_id}' must be an object.")
            malformed.add(block_id)
            continue

        block_type = b.get("type")
        if block_type not in registered:
            problems.append(f"Block '{block_id}' has unknown type '{block_type}'.")

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
                config = b.get("config") or {}
                rule_outputs = [
                    str(r.get("output", "")).strip()
                    for r in config.get("rules") or [] if isinstance(r, dict)
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

        if block_type == "manual_trigger" and depends_on:
            problems.append(f"Trigger '{block_id}' can't have incoming connections.")

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


def ancestors(definition: dict, block_id: str) -> set[str]:
    """Every block upstream of block_id, following depends_on."""
    block_defs = definition.get("blocks", {})
    found: set[str] = set()
    stack = list(block_defs.get(block_id, {}).get("depends_on", []))
    while stack:
        a = stack.pop()
        if a in found or a not in block_defs:
            continue
        found.add(a)
        stack.extend(block_defs[a].get("depends_on", []))
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
