"""Manual check: an agent survives its worker dying mid tool call. Not run in CI.

    docker compose exec worker python scripts/agent_crash_drill.py

Needs ENABLE_TEST_PROVIDERS=1 on the api and worker (the scripted provider
and /_test/echo). Must run inside the worker container, because it kills the
worker's pool processes while a tool call is in flight; the task is then
redelivered and the agent resumes from its agent_steps checkpoint.

1. side-effecting (POST): after the restart the call is NOT repeated (echo
   count stays 1) and the model is told its outcome is unknown.
2. safe (GET): the call is re-run (echo count 2) and the run finishes.
"""

import json
import os
import signal
import sys
import time
import urllib.request
import uuid

API = os.environ.get("DRILL_API_URL", "http://api:8000")
TAG = f"crash_{uuid.uuid4().hex[:8]}"
failures: list[str] = []


def check(name: str, ok: bool, detail="") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def api(method: str, path: str, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def worker_children() -> list[int]:
    """Celery's pool processes: celery processes whose parent is also celery."""
    me = os.getpid()
    procs: dict[int, int] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == me:
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                if b"celery" not in f.read():
                    continue
            with open(f"/proc/{entry}/stat") as f:
                procs[int(entry)] = int(f.read().rsplit(")", 1)[1].split()[1])
        except OSError:
            continue
    return [pid for pid, parent in procs.items() if parent in procs]


def blk(type_, config, depends_on, next_):
    return {"type": type_, "config": config, "depends_on": depends_on, "next": next_,
            "position": {"x": 0, "y": 0}, "notes": ""}


def definition(method: str, path: str) -> dict:
    tool = {
        # The tool runs in the worker, which reaches the API at the same base URL as this script.
        "method": method, "url": f"{API}/_test/echo/{TAG}/{path}?delay_ms=10000",
        "authentication": "none", "timeout_seconds": 30,
        "tool_name": "slow_call", "tool_description": "A slow echo call used by the crash drill.",
        "tool_parameters": {"type": "object", "properties": {"n": {"type": "integer"}}},
    }
    agent = {
        "provider": "scripted", "model": "scripted", "task": "call it", "tools": ["slow"],
        "tool_timeout_seconds": 60,
        "script": [{"tool_calls": [{"name": "slow_call", "args": {"n": 1}}]}, {"text": "checked"}],
    }
    return {"blocks": {
        "trigger": blk("manual_trigger", {}, [], ["agent_1"]),
        "agent_1": blk("agent", agent, ["trigger"], []),
        "slow": blk("http_request", tool, [], []),
    }}


def count(path: str) -> int:
    return api("GET", f"/_test/echo/count?path=/_test/echo/{TAG}/{path}")["count"]


def agent_block(run_id: str) -> dict:
    return next(b for b in api("GET", f"/runs/{run_id}/blocks") if b["block_id"] == "agent_1")


def drill(name: str, method: str, path: str) -> tuple[str, dict]:
    pid = api("POST", "/pipelines", {"name": f"agent_crash_drill_{TAG}_{path}", "definition": definition(method, path)})["id"]
    run_id = api("POST", "/runs", {"pipeline_id": pid})["run_id"]

    deadline = time.time() + 30
    while count(path) == 0 and time.time() < deadline:
        time.sleep(0.2)
    check(f"{name}: the tool call reached the endpoint", count(path) == 1)
    time.sleep(1)  # well inside the 10 s delay
    children = worker_children()
    check(f"{name}: found the worker's pool processes", bool(children))
    for p in children:
        os.kill(p, signal.SIGKILL)
    print(f"      killed {len(children)} pool process(es) mid-call")

    deadline = time.time() + 120
    run = api("GET", f"/runs/{run_id}")
    while run["status"] not in ("succeeded", "failed") and time.time() < deadline:
        time.sleep(1)
        run = api("GET", f"/runs/{run_id}")
    check(f"{name}: the run finishes after the restart", run["status"] == "succeeded",
          f"{run['status']} {run.get('error_summary')}")
    block = agent_block(run_id)
    api("DELETE", f"/pipelines/{pid}")
    return run["status"], block


def main() -> int:
    status, block = drill("side-effecting POST", "POST", "post")
    time.sleep(10)  # let the orphaned request finish on the API, so it is counted
    check("side-effecting POST: the call was not repeated (count stays 1)", count("post") == 1, count("post"))
    trace = (block.get("output") or {}).get("trace") or []
    tool = next((t for t in trace if t["kind"] == "tool"), {})
    check("side-effecting POST: the model got the 'outcome unknown' observation",
          tool.get("outcome_unknown") is True and "outcome of this call is unknown" in str(tool.get("response")),
          f"{tool}")
    check("side-effecting POST: the step is marked failed", tool.get("status") == "failed")

    status, block = drill("safe GET", "GET", "get")
    time.sleep(10)
    check("safe GET: the call was re-run (count 2)", count("get") == 2, count("get"))
    trace = (block.get("output") or {}).get("trace") or []
    tool = next((t for t in trace if t["kind"] == "tool"), {})
    check("safe GET: the re-run call completed", tool.get("status") == "completed", f"{tool}")

    print(f"\n{'All drills passed.' if not failures else f'{len(failures)} check(s) failed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
