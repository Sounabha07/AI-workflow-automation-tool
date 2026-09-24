"""End-to-end smoke test against a running stack (docker compose up).

A Python port of the manual smoke-test.ps1 checks, used by CI's
integration-smoke job. Standard library only. Every HTTP block calls the
API's own /health endpoint over the docker network (http://api:8000), so
nothing depends on third-party services or credentials.

    python scripts/smoke_test.py            # against http://localhost:8000
    SMOKE_BASE_URL=http://host:8000 python scripts/smoke_test.py

Prints PASS/FAIL per check and exits 1 if any check fails.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("SMOKE_BASE_URL", "http://localhost:8000").rstrip("/")
PREFIX = f"smoke_{time.strftime('%H%M%S')}"
HEALTH = "http://api:8000/health"  # the worker reaches the API through the docker network

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def section(title):
    print(f"\n{title}")


def api(method, path, body=None):
    """Returns (status, parsed JSON or None, raw error text)."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None), ""
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw), raw
        except json.JSONDecodeError:
            return e.code, None, raw


def blk(type_, config, depends_on, next_, x):
    return {"type": type_, "config": config, "depends_on": list(depends_on), "next": next_,
            "position": {"x": x, "y": 200}, "notes": ""}


def http_cfg(url):
    return {"method": "GET", "url": url, "authentication": "none", "send_headers": False,
            "send_query_params": False, "send_body": False, "timeout_seconds": 10}


def new_pipe(suffix, definition):
    status, data, err = api("POST", "/pipelines", {"name": f"{PREFIX}_{suffix}", "definition": definition})
    if status != 201:
        raise RuntimeError(f"Could not create {PREFIX}_{suffix} ({status}): {err}")
    return data["id"]


def start_run(pipeline_id, input_data=None):
    status, data, err = api("POST", "/runs", {"pipeline_id": pipeline_id, "input_data": input_data or {}})
    if status != 202:
        raise RuntimeError(f"Could not start run ({status}): {err}")
    return data["run_id"]


def wait_run(run_id, timeout=60):
    """Polls GET /runs/{id} until it finishes; None on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, data, _ = api("GET", f"/runs/{run_id}")
        if data and data.get("status") in ("succeeded", "failed"):
            return data
        time.sleep(0.5)
    return None


def block_of(run_id, block_id):
    _, data, _ = api("GET", f"/runs/{run_id}/blocks")
    return next((b for b in data or [] if b["block_id"] == block_id), {})


def status_of(run):
    return run["status"] if run else "timed out"


def main():
    section("1. Health and block registry")
    _, h, err = api("GET", "/health")
    check("GET /health reports ok", (h or {}).get("status") == "ok", err)
    _, blocks, _ = api("GET", "/blocks")
    types = [b["type"] for b in blocks or []]
    check("four block types registered", len(types) == 4, f"got: {types}")
    check("switch block is registered", "switch" in types)
    check("every block schema has a category", all(b["schema"].get("category") for b in blocks or []))

    section("2. Definition validation")
    cycle = {"blocks": {
        "t": blk("manual_trigger", {}, [], ["a"], 0),
        "a": blk("http_request", http_cfg(HEALTH), ["t", "b"], ["b"], 200),
        "b": blk("http_request", http_cfg(HEALTH), ["a"], ["a"], 400)}}
    status, data, _ = api("POST", "/pipelines", {"name": f"{PREFIX}_cycle", "definition": cycle})
    check("a cycle is rejected with 400", status == 400, f"status {status}")
    check("the 400 lists problems", bool((data or {}).get("problems")))
    self_loop = {"blocks": {
        "t": blk("manual_trigger", {}, [], ["a"], 0),
        "a": blk("http_request", http_cfg(HEALTH), ["t", "a"], ["a"], 200)}}
    status, _, _ = api("POST", "/pipelines", {"name": f"{PREFIX}_self", "definition": self_loop})
    check("a self-loop is rejected with 400", status == 400, f"status {status}")

    section("3. Input block, resolver and HTTP block")
    fields = [{"name": "path", "label": "Path", "type": "text", "required": True, "description": ""}]
    linear = {"blocks": {
        "trigger": blk("manual_trigger", {}, [], ["inp"], 0),
        "inp": blk("input_block", {"fields": fields}, ["trigger"], ["call"], 200),
        "call": blk("http_request", http_cfg("http://api:8000/{{ inp.values.path }}"), ["inp"], [], 400)}}
    linear_id = new_pipe("linear", linear)
    run = wait_run(start_run(linear_id, {"path": "health"}))
    check("run with input_data succeeds", status_of(run) == "succeeded", f"status {status_of(run)}")
    if run:
        inp = block_of(run["id"], "inp")
        check("input block outputs the supplied value", (inp.get("output") or {}).get("values", {}).get("path") == "health")
        call = block_of(run["id"], "call")
        check("HTTP call resolved {{ inp.values.path }} and got data back",
              ((call.get("output") or {}).get("data") or {}).get("status") == "ok", f"output: {call.get('output')}")
    run = wait_run(start_run(linear_id, {}))
    check("missing required input fails the run", status_of(run) == "failed", f"status {status_of(run)}")

    section("4. Switch branching and fan-in")
    sw = {"value": "50", "rules": [{"operator": "greater_than", "compare_value": "10", "output": "big"}], "fallback": True}
    with_input = {"blocks": {
        "trigger": blk("manual_trigger", {}, [], ["route", "inp"], 0),
        "inp": blk("input_block", {"fields": []}, ["trigger"], ["fallback_call"], 200),
        "route": blk("switch", sw, ["trigger"], {"big": ["big_call"], "fallback": ["fallback_call"]}, 200),
        "big_call": blk("http_request", http_cfg(HEALTH), ["route"], [], 400),
        "fallback_call": blk("http_request", http_cfg(HEALTH), ["route", "inp"], [], 400)}}
    run = wait_run(start_run(new_pipe("fanin", with_input)))
    check("fan-in run succeeds", status_of(run) == "succeeded", f"status {status_of(run)}")
    if run:
        check("switch took the big branch", (block_of(run["id"], "route").get("output") or {}).get("branch_taken") == "big")
        check("big_call ran", block_of(run["id"], "big_call").get("status") == "succeeded")
        fc = block_of(run["id"], "fallback_call").get("status")
        check("fallback_call still ran through its live input edge", fc == "succeeded", f"status {fc}")

    no_input = {"blocks": {
        "trigger": blk("manual_trigger", {}, [], ["route"], 0),
        "route": blk("switch", sw, ["trigger"], {"big": ["big_call"], "fallback": ["fallback_call"]}, 200),
        "big_call": blk("http_request", http_cfg(HEALTH), ["route"], [], 400),
        "fallback_call": blk("http_request", http_cfg(HEALTH), ["route"], [], 400)}}
    branch_id = new_pipe("branch", no_input)
    run = wait_run(start_run(branch_id))
    check("branch run succeeds", status_of(run) == "succeeded", f"status {status_of(run)}")
    branch_run_id = run["id"] if run else None
    if run:
        fc = block_of(run["id"], "fallback_call").get("status")
        check("untaken fallback_call is skipped", fc == "skipped", f"status {fc}")

    low = {**sw, "value": "5"}
    low_def = {"blocks": {**no_input["blocks"],
                          "route": blk("switch", low, ["trigger"], {"big": ["big_call"], "fallback": ["fallback_call"]}, 200)}}
    run = wait_run(start_run(new_pipe("branch_low", low_def)))
    if run:
        check("value 5 takes the fallback branch", (block_of(run["id"], "route").get("output") or {}).get("branch_taken") == "fallback")
        check("big_call is skipped when value is 5", block_of(run["id"], "big_call").get("status") == "skipped")
        check("fallback_call runs when value is 5", block_of(run["id"], "fallback_call").get("status") == "succeeded")
    else:
        check("low-value branch run finishes", False, "timed out")

    section("5. Bad references fail cleanly")
    bad = {"blocks": {
        "trigger": blk("manual_trigger", {}, [], ["call"], 0),
        "call": blk("http_request", http_cfg("http://api:8000/{{ missing.field }}"), ["trigger"], [], 200)}}
    run = wait_run(start_run(new_pipe("badref", bad)), timeout=20)
    check("run fails instead of hanging", status_of(run) == "failed", f"status {status_of(run)}")
    summary = (run or {}).get("error_summary") or {}
    check("error_summary names the failing block", summary.get("block_id") == "call")
    check("error is marked not retryable", summary.get("retryable") is False)
    check("error message mentions the missing block", "missing" in (summary.get("message") or ""))

    section("6. Not found returns 404")
    g = uuid.uuid4()
    check("GET /pipelines/<random> is 404", api("GET", f"/pipelines/{g}")[0] == 404)
    check("GET /runs/<random> is 404", api("GET", f"/runs/{g}")[0] == 404)
    check("GET /runs/<random>/blocks is 404", api("GET", f"/runs/{g}/blocks")[0] == 404)

    section("7. Run history filters")
    _, data, _ = api("GET", f"/runs?pipeline_name={PREFIX}&status=failed")
    items = (data or {}).get("items", [])
    check("failed filter returns this test's failed runs", len(items) >= 2, f"got {len(items)}")
    check("every item is failed", all(i["status"] == "failed" for i in items))
    check("every item matches the name filter", all(i["pipeline_name"].startswith(PREFIX) for i in items))
    _, data, _ = api("GET", f"/runs?pipeline_name={PREFIX.upper()}")
    check("name filter is case-insensitive", len((data or {}).get("items", [])) >= 1)

    section("8. Active toggle and auto-activation")
    before = api("GET", f"/pipelines/{branch_id}")[1]["updated_at"]
    _, data, err = api("PATCH", f"/pipelines/{branch_id}", {"is_active": True})
    check("PATCH turns the workflow active", (data or {}).get("is_active") is True, err)
    listed = next((p for p in api("GET", "/pipelines")[1] if p["id"] == branch_id), {})
    check("list shows it as active", listed.get("is_active") is True)
    check("list includes block_count", listed.get("block_count") == 4, f"got {listed.get('block_count')}")
    check("toggling does not change updated_at", api("GET", f"/pipelines/{branch_id}")[1]["updated_at"] == before)
    api("PATCH", f"/pipelines/{branch_id}", {"is_active": False})
    _, data, _ = api("POST", "/runs", {"pipeline_id": branch_id, "input_data": {}})
    check("POST /runs reports pipeline_is_active", (data or {}).get("pipeline_is_active") is True)
    check("running a workflow activates it", api("GET", f"/pipelines/{branch_id}")[1]["is_active"] is True)
    if data:
        wait_run(data["run_id"])

    section("9. Test step")
    status, data, err = api("POST", "/runs/test", {"pipeline_id": branch_id, "block_id": "big_call",
                                                   "input_data": {}, "definition": no_input})
    check("POST /runs/test returns 202", status == 202, f"status {status} {err}")
    test_run = wait_run(data["run_id"]) if data else None
    check("test run succeeds", status_of(test_run) == "succeeded", f"status {status_of(test_run)}")
    hist = [i["id"] for i in api("GET", f"/runs?pipeline_name={PREFIX}_branch")[1]["items"]]
    check("test run is hidden from history", bool(test_run) and test_run["id"] not in hist)
    lo = api("GET", f"/pipelines/{branch_id}/latest-outputs")[1] or {}
    check("latest-outputs includes the tested block", "big_call" in lo)

    section("10. Deleting a workflow deletes its run history")
    check("DELETE of a workflow with runs returns 204", api("DELETE", f"/pipelines/{branch_id}")[0] == 204)
    check("the pipeline is gone", api("GET", f"/pipelines/{branch_id}")[0] == 404)
    if branch_run_id:
        check("its runs are gone too", api("GET", f"/runs/{branch_run_id}")[0] == 404)
    remaining = [i for i in api("GET", f"/runs?pipeline_name={PREFIX}_branch&limit=200")[1]["items"]
                 if i["pipeline_id"] == branch_id]
    check("history no longer lists its runs", remaining == [], f"{len(remaining)} left")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # a crash is a failure, with the reason visible in the log
        print(f"\nSMOKE TEST CRASHED: {type(e).__name__}: {e}")
        sys.exit(1)
