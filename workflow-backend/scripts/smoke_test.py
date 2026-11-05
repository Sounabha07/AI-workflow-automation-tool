"""End-to-end smoke test against a running stack (docker compose up).

A Python port of the manual smoke-test.ps1 checks, used by CI's
integration-smoke job. Standard library only. Every HTTP block calls the
API's own /health endpoint over the docker network (http://api:8000), so
nothing depends on third-party services or credentials.

    python scripts/smoke_test.py            # against http://localhost:8000
    SMOKE_BASE_URL=http://host:8000 python scripts/smoke_test.py

Prints PASS/FAIL per check and exits 1 if any check fails.
"""

import hashlib
import hmac
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


def api(method, path, body=None, raw=None, headers=None):
    """Returns (status, parsed JSON or None, raw error text). `raw` sends
    those exact bytes instead of JSON-encoding `body`."""
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
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


def wait_block(run_id, block_id, statuses, timeout=30):
    """Polls until block_id reaches one of statuses; returns the block."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        b = block_of(run_id, block_id)
        if b.get("status") in statuses:
            return b
        time.sleep(0.3)
    return block_of(run_id, block_id)


def token_of(url):
    return (url or "").rstrip("/").rsplit("/", 1)[-1]


def pipeline_runs(pipeline_id):
    return api("GET", f"/pipelines/{pipeline_id}/runs")[1] or []


def problems_of(data):
    return (data or {}).get("problems", [])


def wait_cfg(timeout_seconds):
    return {"timeout_seconds": timeout_seconds, "description": ""}


def main():
    section("1. Health and block registry")
    _, h, err = api("GET", "/health")
    check("GET /health reports ok", (h or {}).get("status") == "ok", err)
    _, blocks, _ = api("GET", "/blocks")
    types = [b["type"] for b in blocks or []]
    check("nine block types registered", len(types) == 9, f"got: {types}")
    check("switch block is registered", "switch" in types)
    for t in ("schedule_trigger", "webhook_trigger", "wait_for_input"):
        check(f"{t} block is registered", t in types)
    llm = next((b for b in blocks or [] if b["type"] == "llm"), None)
    check("llm block is registered with category llm", bool(llm) and llm["schema"]["category"] == "llm")

    # Started early: its first tick (up to a minute away) overlaps the rest.
    sched_id, sched_started = schedule_setup_checks()
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
    # Validation only: nothing here reaches an LLM provider.
    bad_llm = {"blocks": {
        "t": blk("manual_trigger", {}, [], ["l"], 0),
        "l": blk("llm", {"provider": "nope", "prompt": " ", "temperature": 5}, ["t"], [], 200)}}
    status, data, _ = api("POST", "/pipelines", {"name": f"{PREFIX}_llm_bad", "definition": bad_llm})
    problems = " ".join((data or {}).get("problems") or [])
    check("a bad llm config is rejected with 400", status == 400, f"status {status}")
    check("the 400 names the provider, prompt and temperature",
          all(w in problems for w in ("unknown provider", "prompt", "temperature")), problems)

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

    section("10. Saved credentials (no LLM is ever called)")
    secret = f"AIza-smoke-{uuid.uuid4().hex}"
    cred_name = f"{PREFIX}_cred"
    status, cred, err = api("POST", "/credentials",
                            {"name": cred_name, "type": "gemini_api_key", "data": {"api_key": secret}})
    check("POST /credentials returns 201", status == 201, f"status {status} {err}")
    check("the response never contains the secret", secret not in json.dumps(cred))
    check("the response shows a hint of the last 4 characters", (cred or {}).get("hint") == "…" + secret[-4:])
    listed = api("GET", "/credentials")[1] or []
    check("GET /credentials lists it without the secret",
          any(c["id"] == (cred or {}).get("id") for c in listed) and secret not in json.dumps(listed))
    status, _, _ = api("POST", "/credentials", {"name": cred_name, "type": "gemini_api_key", "data": {"api_key": "x" * 20}})
    check("a duplicate name is rejected with 409", status == 409, f"status {status}")
    status, _, _ = api("POST", "/credentials", {"name": f"{cred_name}_bad", "type": "nope", "data": {"api_key": "x"}})
    check("an unknown credential type is rejected with 400", status == 400, f"status {status}")
    with_key = {"blocks": {"t": blk("manual_trigger", {}, [], ["l"], 0),
                           "l": blk("llm", {"prompt": "hi", "api_key": "AIza-plain"}, ["t"], [], 200)}}
    status, _, _ = api("POST", "/pipelines", {"name": f"{PREFIX}_llm_plainkey", "definition": with_key})
    check("a plain API key in a workflow is rejected with 400", status == 400, f"status {status}")
    if cred:
        uses = {"blocks": {"t": blk("manual_trigger", {}, [], ["l"], 0),
                           "l": blk("llm", {"prompt": "hi", "credential": cred["id"]}, ["t"], [], 200)}}
        uses_id = new_pipe("llm_cred", uses)
        status, _, err = api("DELETE", f"/credentials/{cred['id']}")
        check("deleting a credential in use is rejected with 409", status == 409 and "llm_cred" in err, f"status {status}")
        api("DELETE", f"/pipelines/{uses_id}")
        check("an unused credential can be deleted", api("DELETE", f"/credentials/{cred['id']}")[0] == 204)
    # A credential id that doesn't exist fails at run time, once, before any network call.
    gone = {"blocks": {"t": blk("manual_trigger", {}, [], ["l"], 0),
                       "l": blk("llm", {"prompt": "hi", "credential": str(uuid.uuid4())}, ["t"], [], 200)}}
    run = wait_run(start_run(new_pipe("llm_gone", gone)))
    err_l = (run and block_of(run["id"], "l").get("error")) or {}
    check("a missing credential fails once, not retryable",
          status_of(run) == "failed" and err_l.get("attempts") == 1 and err_l.get("retryable") is False
          and "no longer exists" in err_l.get("message", ""), json.dumps(err_l))

    section("11. Deleting a workflow deletes its run history")
    check("DELETE of a workflow with runs returns 204", api("DELETE", f"/pipelines/{branch_id}")[0] == 204)
    check("the pipeline is gone", api("GET", f"/pipelines/{branch_id}")[0] == 404)
    if branch_run_id:
        check("its runs are gone too", api("GET", f"/runs/{branch_run_id}")[0] == 404)
    remaining = [i for i in api("GET", f"/runs?pipeline_name={PREFIX}_branch&limit=200")[1]["items"]
                 if i["pipeline_id"] == branch_id]
    check("history no longer lists its runs", remaining == [], f"{len(remaining)} left")

    validation_checks()
    wait_checks(linear_id)
    wait_fixed_link_checks()
    wait_timeout_checks()
    webhook_checks()
    agent_checks(blocks or [])
    schedule_fire_checks(sched_id, sched_started)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


def schedule_setup_checks():
    section("1b. Schedule trigger: validation, preview, activation")
    status, data, _ = api("POST", "/schedule/preview", {"cron": "*/5 * * * *", "timezone": "Europe/London"})
    times = (data or {}).get("times", [])
    check("preview returns the next 5 fire times", status == 200 and len(times) == 5, f"{status} {data}")
    check("preview times are increasing", times == sorted(times) and len(set(times)) == 5)
    check("preview rejects a bad cron with 400", api("POST", "/schedule/preview", {"cron": "61 * * * *"})[0] == 400)
    check("preview rejects a bad timezone with 400",
          api("POST", "/schedule/preview", {"cron": "* * * * *", "timezone": "Mars/Base"})[0] == 400)
    bad = {"blocks": {"sched": blk("schedule_trigger", {"cron": "every minute", "timezone": "UTC"}, [], [], 0)}}
    status, data, _ = api("POST", "/pipelines", {"name": f"{PREFIX}_badcron", "definition": bad})
    check("a pipeline with a bad cron is rejected", status == 400 and any("cron" in p for p in problems_of(data)))
    bad_tz = {"blocks": {"sched": blk("schedule_trigger", {"cron": "* * * * *", "timezone": "Mars/Base"}, [], [], 0)}}
    status, data, _ = api("POST", "/pipelines", {"name": f"{PREFIX}_badtz", "definition": bad_tz})
    check("a pipeline with a bad timezone is rejected", status == 400 and any("timezone" in p for p in problems_of(data)))

    sched_def = {"blocks": {
        "sched": blk("schedule_trigger", {"cron": "* * * * *", "timezone": "UTC"}, [], ["call"], 0),
        "call": blk("http_request", http_cfg(HEALTH), ["sched"], [], 200)}}
    sched_id = new_pipe("sched", sched_def)
    trig = (api("GET", f"/pipelines/{sched_id}")[1] or {}).get("triggers", [])
    check("the schedule is listed as a trigger with a next run", bool(trig) and bool(trig[0].get("next_run_at")), f"{trig}")
    listed = next((p for p in api("GET", "/pipelines")[1] if p["id"] == sched_id), {})
    check("list shows trigger_type schedule", listed.get("trigger_type") == "schedule", f"{listed}")
    check("an inactive schedule shows no next run in the list", listed.get("next_run_at") is None)
    api("PATCH", f"/pipelines/{sched_id}", {"is_active": True})
    listed = next((p for p in api("GET", "/pipelines")[1] if p["id"] == sched_id), {})
    check("an active schedule shows its next run in the list", bool(listed.get("next_run_at")))
    return sched_id, time.monotonic()


def validation_checks():
    section("11. Validation: one trigger, reserved ids, resume refs")
    two = {"blocks": {"t": blk("manual_trigger", {}, [], [], 0), "h": blk("webhook_trigger", {}, [], [], 200)}}
    status, data, _ = api("POST", "/pipelines", {"name": f"{PREFIX}_two", "definition": two})
    check("two triggers are rejected", status == 400 and any("only one trigger" in p for p in problems_of(data)))
    none = {"blocks": {"a": blk("http_request", http_cfg(HEALTH), [], [], 0)}}
    status, data, _ = api("POST", "/pipelines", {"name": f"{PREFIX}_none", "definition": none})
    check("no trigger is rejected", status == 400 and any("needs a trigger" in p for p in problems_of(data)))
    reserved = {"blocks": {
        "t": blk("manual_trigger", {}, [], ["resume"], 0),
        "resume": blk("http_request", http_cfg(HEALTH), ["t"], [], 200)}}
    status, data, _ = api("POST", "/pipelines", {"name": f"{PREFIX}_reserved", "definition": reserved})
    check("block id 'resume' is rejected", status == 400 and any("reserved" in p for p in problems_of(data)))
    badref = {"blocks": {
        "t": blk("manual_trigger", {}, [], ["call"], 0),
        "call": blk("http_request", http_cfg("http://api:8000/health?x={{ resume.call.url }}"), ["t"], [], 200)}}
    status, data, _ = api("POST", "/pipelines", {"name": f"{PREFIX}_resref", "definition": badref})
    check("a resume ref to a non-wait block is rejected",
          status == 400 and any("resume.call" in p for p in problems_of(data)), f"{status} {data}")
    bad_wait = {"blocks": {
        "t": blk("manual_trigger", {}, [], ["w"], 0),
        "w": blk("wait_for_input", wait_cfg(0), ["t"], [], 200)}}
    status, data, _ = api("POST", "/pipelines", {"name": f"{PREFIX}_badwait", "definition": bad_wait})
    check("a wait timeout of 0 is rejected", status == 400 and any("timeout_seconds" in p for p in problems_of(data)))


def wait_checks(plain_pipeline_id):
    section("12. Wait for input: park, notify, resume, run on")
    wait_def = {"blocks": {
        "trigger": blk("manual_trigger", {}, [], ["inp"], 0),
        "inp": blk("input_block", {"fields": []}, ["trigger"], ["notify"], 200),
        # The notifier runs BEFORE the wait block but already knows its link.
        "notify": blk("http_request", http_cfg("http://api:8000/health?link={{ resume.wait.url }}"), ["inp"], ["wait"], 400),
        "wait": blk("wait_for_input", wait_cfg(300), ["notify"], ["after"], 600),
        "after": blk("http_request", http_cfg("http://api:8000/{{ wait.data.path }}"), ["wait"], [], 800)}}
    run_id = start_run(new_pipe("wait", wait_def))
    wb = wait_block(run_id, "wait", ("waiting", "failed", "succeeded"))
    check("the wait block parks as waiting", wb.get("status") == "waiting", f"{wb.get('status')} {wb.get('error')}")
    check("a waiting block exposes its resume URL and deadline", bool(wb.get("resume_url")) and bool(wb.get("wait_deadline")))
    check("downstream stays pending", block_of(run_id, "after").get("status") == "pending")
    check("the run stays running", (api("GET", f"/runs/{run_id}")[1] or {}).get("status") == "running")
    notify_url = (block_of(run_id, "notify").get("resolved_config") or {}).get("url") or ""
    check("the upstream notifier got the resume URL",
          bool(wb.get("resume_url")) and notify_url.endswith(wb.get("resume_url", "")), f"{notify_url} vs {wb.get('resume_url')}")
    other = wait_run(start_run(plain_pipeline_id, {"path": "health"}))
    check("another workflow still runs while one waits", status_of(other) == "succeeded", f"status {status_of(other)}")

    token = token_of(wb.get("resume_url"))
    check("resume rejects a non-object body with 400", api("POST", f"/resume/{token}", [1, 2])[0] == 400)
    check("resume rejects a body over 1 MB with 413",
          api("POST", f"/resume/{token}", raw=b'{"x":"' + b"a" * (1024 * 1024) + b'"}')[0] == 413)
    status, data, err = api("POST", f"/resume/{token}", {"path": "health"})
    check("resume returns 200 {run_id, block_id, status}",
          status == 200 and (data or {}).get("run_id") == run_id and (data or {}).get("block_id") == "wait"
          and (data or {}).get("status") == "succeeded", f"{status} {data} {err}")
    check("a second resume returns 409", api("POST", f"/resume/{token}", {"path": "health"})[0] == 409)
    run = wait_run(run_id)
    check("the resumed run succeeds", status_of(run) == "succeeded", f"status {status_of(run)}")
    out = block_of(run_id, "wait").get("output") or {}
    check("wait output is {data, resumed_at}", out.get("data") == {"path": "health"} and bool(out.get("resumed_at")), f"{out}")
    after = block_of(run_id, "after")
    check("{{ wait.data.path }} resolved downstream",
          ((after.get("output") or {}).get("data") or {}).get("status") == "ok", f"{after}")
    check("downstream ran once, without retries", after.get("status") == "succeeded" and after.get("retry_count") == 0)
    check("an unknown resume token is 404", api("POST", "/resume/not-a-real-token", {})[0] == 404)


def wait_fixed_link_checks():
    section("12b. Wait for input: the block's fixed resume URL")
    d = {"blocks": {
        "trigger": blk("manual_trigger", {}, [], ["wait"], 0),
        "wait": blk("wait_for_input", wait_cfg(300), ["trigger"], [], 200)}}
    pid = new_pipe("wait_link", d)
    links = (api("GET", f"/pipelines/{pid}")[1] or {}).get("resume_links", [])
    url = links[0]["url"] if links else None
    check("a saved wait block has a fixed resume URL", bool(url) and "/resume/" in url, f"{links}")
    path = "/resume/" + token_of(url)
    check("with nothing waiting it returns 409", api("POST", path, {})[0] == 409)
    api("PUT", f"/pipelines/{pid}", {"definition": d})
    again = (api("GET", f"/pipelines/{pid}")[1] or {}).get("resume_links", [])
    check("the fixed URL is stable across saves", bool(again) and again[0]["url"] == url)
    first, second = start_run(pid), None
    wait_block(first, "wait", ("waiting",))
    second = start_run(pid)
    wait_block(second, "wait", ("waiting",))
    s1, d1, _ = api("POST", path, {"n": 1})
    s2, d2, _ = api("POST", path, {"n": 2})
    check("the fixed URL resumes the longest-waiting run first",
          s1 == 200 and s2 == 200 and (d1 or {}).get("run_id") == first and (d2 or {}).get("run_id") == second,
          f"{s1} {d1} {s2} {d2}")
    check("each run got its own JSON",
          (block_of(first, "wait").get("output") or {}).get("data") == {"n": 1}
          and (block_of(second, "wait").get("output") or {}).get("data") == {"n": 2})
    check("with both resumed it returns 409 again", api("POST", path, {})[0] == 409)
    api("DELETE", f"/pipelines/{pid}")
    check("after deleting the workflow it returns 404", api("POST", path, {})[0] == 404)


def wait_timeout_checks():
    section("13. Wait for input: timeout and cancellation")
    timeout_def = {"blocks": {
        "trigger": blk("manual_trigger", {}, [], ["wait"], 0),
        "wait": blk("wait_for_input", wait_cfg(5), ["trigger"], ["after"], 200),
        "after": blk("http_request", http_cfg(HEALTH), ["wait"], [], 400)}}
    started = time.monotonic()
    run_id = start_run(new_pipe("wait_timeout", timeout_def))
    token = token_of(wait_block(run_id, "wait", ("waiting",)).get("resume_url"))
    run = wait_run(run_id, timeout=45)
    elapsed = time.monotonic() - started
    check("an unresumed wait fails the run", status_of(run) == "failed", f"status {status_of(run)}")
    check("...within ~20s of a 5s timeout", run is not None and elapsed < 25, f"{elapsed:.1f}s")
    summary = (run or {}).get("error_summary") or {}
    check("the error is a non-retryable timeout",
          summary.get("block_id") == "wait" and summary.get("retryable") is False
          and "Timed out waiting for input after 5 seconds" in (summary.get("message") or ""), f"{summary}")
    check("downstream of a timed-out wait stays pending", block_of(run_id, "after").get("status") == "pending")
    check("resuming a timed-out wait returns 410", api("POST", f"/resume/{token}", {})[0] == 410)

    cancel_def = {"blocks": {
        "trigger": blk("manual_trigger", {}, [], ["long_wait", "short_wait"], 0),
        "long_wait": blk("wait_for_input", wait_cfg(300), ["trigger"], [], 200),
        # The parallel branch that fails, deterministically after long_wait parks.
        "short_wait": blk("wait_for_input", wait_cfg(2), ["trigger"], [], 200)}}
    run_id = start_run(new_pipe("wait_cancel", cancel_def))
    token = token_of(wait_block(run_id, "long_wait", ("waiting",)).get("resume_url"))
    run = wait_run(run_id, timeout=45)
    check("a failing parallel branch fails the run", status_of(run) == "failed", f"status {status_of(run)}")
    lw = block_of(run_id, "long_wait").get("status")
    check("the other waiting block is cancelled", lw == "cancelled", f"status {lw}")
    check("resuming a cancelled wait returns 410", api("POST", f"/resume/{token}", {})[0] == 410)


def webhook_checks():
    section("14. Webhook trigger")
    hook_def = {"blocks": {
        "hook": blk("webhook_trigger", {"secret": "", "signature_header": "X-Hub-Signature-256"}, [], ["call"], 0),
        "call": blk("http_request", http_cfg("http://api:8000/{{ hook.body.path }}"), ["hook"], [], 200)}}
    hook_id = new_pipe("hook", hook_def)
    trig = (api("GET", f"/pipelines/{hook_id}")[1] or {}).get("triggers", [])
    url = trig[0].get("webhook_url") if trig else None
    check("GET pipeline exposes the full webhook URL", bool(url) and "/hooks/" in url, f"{trig}")
    hook_path = "/hooks/" + token_of(url)
    check("an inactive workflow's webhook returns 409", api("POST", hook_path, {"path": "health"})[0] == 409)
    check("...and creates no run", pipeline_runs(hook_id) == [])
    api("PUT", f"/pipelines/{hook_id}", {"definition": hook_def})
    trig = (api("GET", f"/pipelines/{hook_id}")[1] or {}).get("triggers", [])
    check("the webhook URL is stable across saves", bool(trig) and trig[0].get("webhook_url") == url)
    api("PATCH", f"/pipelines/{hook_id}", {"is_active": True})
    status, data, err = api("POST", hook_path + "?source=smoke", {"path": "health"},
                            headers={"Authorization": "Bearer nope", "Cookie": "a=b", "X-Custom": "yes"})
    check("webhook returns 202 with a run_id", status == 202 and bool((data or {}).get("run_id")), f"{status} {err}")
    run = wait_run(data["run_id"]) if data else None
    check("the webhook run succeeds", status_of(run) == "succeeded", f"status {status_of(run)}")
    if run:
        check("the run is marked trigger_type webhook", run.get("trigger_type") == "webhook")
        out = block_of(run["id"], "hook").get("output") or {}
        headers = out.get("headers") or {}
        check("trigger output has method, body, query and headers",
              out.get("method") == "POST" and out.get("body") == {"path": "health"}
              and out.get("query") == {"source": "smoke"} and headers.get("x-custom") == "yes", f"{out}")
        check("authorization and cookie headers are dropped", not {"authorization", "cookie"} & set(headers))
        call = block_of(run["id"], "call")
        check("{{ hook.body.path }} reached downstream", ((call.get("output") or {}).get("data") or {}).get("status") == "ok")
    check("an unknown webhook token is 404", api("POST", "/hooks/not-a-real-token", {})[0] == 404)
    check("a webhook body over 1 MB is 413", api("POST", hook_path, raw=b"x" * (1024 * 1024 + 1))[0] == 413)

    before = len(pipeline_runs(hook_id))
    key = {"Idempotency-Key": f"{PREFIX}-delivery-1"}
    s1, d1, _ = api("POST", hook_path, {"path": "health"}, headers=key)
    s2, d2, _ = api("POST", hook_path, {"path": "health"}, headers=key)
    check("a repeated delivery id returns the same run_id with 200",
          s1 == 202 and s2 == 200 and (d1 or {}).get("run_id") == (d2 or {}).get("run_id"), f"{s1} {d1} {s2} {d2}")
    check("...and creates only one run", len(pipeline_runs(hook_id)) == before + 1)
    status, data, _ = api("POST", hook_path, raw=b"plain text body", headers={"Content-Type": "text/plain"})
    if status == 202:
        wait_run(data["run_id"])
        body = (block_of(data["run_id"], "hook").get("output") or {}).get("body")
        check("a non-JSON body is kept as raw text", body == "plain text body", f"{body!r}")
    else:
        check("a non-JSON body is accepted", False, f"status {status}")

    status, data, _ = api("POST", "/runs", {"pipeline_id": hook_id, "trigger_payload": {"body": {"path": "health"}}})
    run = wait_run(data["run_id"]) if data else None
    check("a webhook workflow can be run manually with a sample payload", status_of(run) == "succeeded",
          f"status {status_of(run)}")

    secret = "smoke-secret"
    signed_def = {"blocks": {
        "hook": blk("webhook_trigger", {"secret": secret, "signature_header": "X-Hub-Signature-256"}, [], [], 0)}}
    signed_id = new_pipe("hook_signed", signed_def)
    api("PATCH", f"/pipelines/{signed_id}", {"is_active": True})
    signed_path = "/hooks/" + token_of(api("GET", f"/pipelines/{signed_id}")[1]["triggers"][0]["webhook_url"])
    body = json.dumps({"n": 1}).encode()
    good = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    check("HMAC: missing signature is 401", api("POST", signed_path, raw=body)[0] == 401)
    check("HMAC: wrong signature is 401",
          api("POST", signed_path, raw=body, headers={"X-Hub-Signature-256": "sha256=" + "0" * 64})[0] == 401)
    check("HMAC: tampered body is 401",
          api("POST", signed_path, raw=b'{"n": 2}', headers={"X-Hub-Signature-256": good})[0] == 401)
    status, data, _ = api("POST", signed_path, raw=body, headers={"X-Hub-Signature-256": good})
    check("HMAC: correct signature is 202", status == 202, f"status {status}")
    if data:
        wait_run(data["run_id"])
        hook = block_of(data["run_id"], "hook")
        check("the signature header is not stored", "x-hub-signature-256" not in ((hook.get("output") or {}).get("headers") or {}))
        check("the secret is masked in resolved_config", (hook.get("resolved_config") or {}).get("secret") not in (None, secret))

    check("deleting a workflow removes its webhook",
          api("DELETE", f"/pipelines/{hook_id}")[0] == 204 and api("POST", hook_path, {"path": "health"})[0] == 404)


# ── Agent block (scripted provider + /_test/echo; needs ENABLE_TEST_PROVIDERS=1) ── #

AGENT_SECRET = "smoke-tool-token-7f3a9c"  # a tool's bearer token; must never show up in outputs


def echo_url(path):
    return f"http://api:8000/_test/echo/{PREFIX}/{path}"


def tool_cfg(method, url, name, params, description=None, **extra):
    return {**http_cfg(url), "method": method, "tool_name": name,
            "tool_description": description or f"Calls the {name} test endpoint and returns what it received.",
            "tool_parameters": params, **extra}


def echo_count(path):
    return (api("GET", f"/_test/echo/count?path=/_test/echo/{PREFIX}/{path}")[1] or {}).get("count", 0)


def agent_def(script, agent_extra=None, tools=None, after=True):
    get_params = {"type": "object", "properties": {"item": {"type": "string"}, "limit": {"type": "integer"}},
                  "required": ["item"]}
    tools = tools or {
        "get_tool": blk("http_request", tool_cfg(
            "GET", echo_url("get/{item}"), "get_item", get_params,
            authentication="bearer", bearer_token=AGENT_SECRET), [], [], 200),
        "post_tool": blk("http_request", tool_cfg(
            "POST", echo_url("post"), "save_note",
            {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]},
            tool_static_fields={"source": "smoke"}), [], [], 200),
        "missing_tool": blk("http_request", tool_cfg(
            "GET", "http://api:8000/_test/does-not-exist", "missing", {"type": "object", "properties": {}}),
            [], [], 200),
    }
    agent_cfg = {"provider": "scripted", "model": "scripted", "task": "Find the failed workflow.",
                 "tools": list(tools), "script": script,
                 "output_schema": {"type": "object", "required": ["workflow_name", "error"],
                                   "properties": {"workflow_name": {"type": "string"}, "error": {"type": "string"}}},
                 **(agent_extra or {})}
    blocks_ = {
        "trigger": blk("manual_trigger", {}, [], ["agent_1"], 0),
        "agent_1": blk("agent", agent_cfg, ["trigger"], ["after"] if after else [], 200),
        **tools,
    }
    if after:
        blocks_["after"] = blk("http_request", http_cfg(echo_url("after?name={{ agent_1.final.workflow_name }}")),
                               ["agent_1"], [], 400)
    return {"blocks": blocks_}


def agent_checks(blocks):
    section("15. Agent block with HTTP tools")
    agent = next((b for b in blocks if b["type"] == "agent"), None)
    check("agent is registered with category ai and usable_as_tool false",
          bool(agent) and agent["schema"]["category"] == "ai" and agent.get("usable_as_tool") is False, f"{agent}")
    http = next((b for b in blocks if b["type"] == "http_request"), {})
    check("http_request is usable as a tool", http.get("usable_as_tool") is True)
    providers = [o["value"] for f in (agent or {}).get("schema", {}).get("fields", [])
                 if f["name"] == "provider" for o in f.get("options", [])]
    if "scripted" not in providers:
        check("the scripted provider is enabled (ENABLE_TEST_PROVIDERS=1)", False, f"providers: {providers}")
        return

    # Validation: each bad definition returns 400 naming the problem.
    def problems_for(definition):
        status, data, _ = api("POST", "/pipelines", {"name": f"{PREFIX}_agent_bad", "definition": definition})
        return status, " ".join(problems_of(data))

    base = agent_def([{"text": "x"}], after=False)
    cases = []
    d = json.loads(json.dumps(base)); d["blocks"]["agent_1"]["config"]["task"] = " "
    cases.append(("an empty task", d, "task can't be empty"))
    d = json.loads(json.dumps(base)); d["blocks"]["post_tool"]["config"]["tool_name"] = "get_item"
    cases.append(("duplicate tool names", d, "Tool names must be unique"))
    d = json.loads(json.dumps(base)); d["blocks"]["post_tool"]["config"]["tool_name"] = "finish"
    cases.append(("a tool named finish", d, "reserved"))
    d = json.loads(json.dumps(base)); d["blocks"]["post_tool"]["config"]["tool_description"] = "too short"
    cases.append(("a short tool description", d, "at least 20 characters"))
    d = json.loads(json.dumps(base)); d["blocks"]["post_tool"]["config"]["tool_parameters"] = {"type": "string"}
    cases.append(("non-object tool parameters", d, '"type": "object"'))
    d = json.loads(json.dumps(base)); d["blocks"]["agent_1"]["config"]["output_schema"] = "[1, 2]"
    cases.append(("a non-object output schema", d, "output schema must be a JSON object"))
    d = json.loads(json.dumps(base)); d["blocks"]["agent_1"]["config"]["max_iterations"] = 99
    cases.append(("max_iterations out of range", d, "max_iterations must be a whole number from 1 to 50"))
    d = json.loads(json.dumps(base)); d["blocks"]["agent_1"]["config"]["tools"].append("trigger")
    cases.append(("a non-HTTP block as a tool", d, "only HTTP Request blocks can be tools"))
    d = json.loads(json.dumps(base))
    d["blocks"]["agent_2"] = blk("agent", {**d["blocks"]["agent_1"]["config"], "tools": ["post_tool"]}, ["trigger"], [], 300)
    d["blocks"]["trigger"]["next"].append("agent_2")
    cases.append(("a tool shared by two agents", d, "more than one agent"))
    d = json.loads(json.dumps(base))
    d["blocks"]["post_tool"]["depends_on"] = ["trigger"]; d["blocks"]["trigger"]["next"].append("post_tool")
    cases.append(("a tool with its own connections", d, "can't have other connections"))
    d = json.loads(json.dumps(base))
    d["blocks"]["later"] = blk("http_request", http_cfg(HEALTH), ["agent_1"], [], 400)
    d["blocks"]["agent_1"]["next"] = ["later"]
    d["blocks"]["post_tool"]["config"]["url"] = echo_url("post?x={{ later.data.status }}")
    cases.append(("a tool referencing a block downstream of its agent", d, "isn't upstream of its agent"))
    for name, definition, needle in cases:
        status, problems = problems_for(definition)
        check(f"validation: {name} is a 400 naming it", status == 400 and needle in problems, f"{status} {problems}")
    d = json.loads(json.dumps(base))
    d["blocks"]["post_tool"]["config"]["tool_parameters"] = {
        "type": "object", "properties": {"note": {"type": "string", "const": "x"}}}
    status, data, err = api("POST", "/pipelines", {"name": f"{PREFIX}_agent_warn", "definition": d})
    check("unsupported schema keywords are a warning, not a failure",
          status == 201 and any("const" in w for w in (data or {}).get("warnings", [])), f"{status} {data or err}")

    # The full run: parallel calls, a 404, invalid args, an unknown tool,
    # plain text without finish, an invalid finish, a 503 from the model
    # (retried, resumed from the checkpoint), then a valid finish.
    script = [
        {"tool_calls": [{"name": "get_item", "args": {"item": "a/b", "limit": 2}},
                        {"name": "save_note", "args": {"note": "hello", "source": "model"}}]},
        {"tool_calls": [{"name": "missing", "args": {}}]},
        {"tool_calls": [{"name": "get_item", "args": {"item": 5}}]},
        {"tool_calls": [{"name": "no_such_tool", "args": {}}]},
        {"text": "It was wf_a."},
        {"finish": {"workflow_name": 1}},
        {"error": 503},
        {"finish": {"workflow_name": "wf_a", "error": "boom"}},
    ]
    pid = new_pipe("agent", agent_def(script))
    run = wait_run(start_run(pid), timeout=90)
    check("the agent run succeeds", status_of(run) == "succeeded", f"status {status_of(run)} {(run or {}).get('error_summary')}")
    if not run:
        return
    check("total_blocks excludes tool blocks", run.get("total_blocks") == 3, f"total_blocks {run.get('total_blocks')}")
    rows = api("GET", f"/runs/{run['id']}/blocks")[1] or []
    check("tool blocks never run on their own (no block_executions rows)",
          not {r["block_id"] for r in rows} & {"get_tool", "post_tool", "missing_tool"}, f"{[r['block_id'] for r in rows]}")
    a = block_of(run["id"], "agent_1")
    out = a.get("output") or {}
    trace = out.get("trace") or []
    tools_ = [t for t in trace if t["kind"] == "tool"]
    check("final is the validated structured answer", out.get("final") == {"workflow_name": "wf_a", "error": "boom"}, f"{out.get('final')}")
    check("stop_reason is finished", out.get("stop_reason") == "finished")
    check("7 iterations (the failed model call doesn't count)", out.get("iterations") == 7, f"{out.get('iterations')}")
    check("usage is summed", (out.get("usage") or {}).get("total_tokens") == 7 * 15, f"{out.get('usage')}")
    check("the 503 was retried once through the block's retry path", a.get("retry_count") == 1, f"{a.get('retry_count')}")
    first_turn = [t for t in tools_ if t["step_index"] == 0]
    check("two tool calls ran in parallel in one turn", len(first_turn) == 2 and all(t["status"] == "completed" for t in first_turn), f"{first_turn}")
    check("steps from before the retry are marked replayed", any(t.get("replayed") for t in trace))
    missing = next((t for t in tools_ if t["tool_name"] == "missing"), {})
    check("a 404 comes back as an observation, not a block failure",
          missing.get("status") == "failed" and (missing.get("response") or {}).get("status") == 404, f"{missing}")
    invalid = next((t for t in tools_ if t["step_index"] == 2), {})
    check("invalid args are an observation", "invalid arguments" in str((invalid.get("response") or {}).get("error")), f"{invalid}")
    unknown = next((t for t in tools_ if t["tool_name"] == "no_such_tool"), {})
    check("an unknown tool is an observation", "no tool named" in str((unknown.get("response") or {}).get("error")))
    check("plain text without finish got one correction", sum(1 for t in trace if t.get("nudge")) == 1)
    bad_finish = [t for t in tools_ if t["tool_name"] == "finish" and t["status"] == "failed"]
    check("the invalid finish was sent back for correction", len(bad_finish) == 1)
    check("the GET tool ran exactly once", echo_count("get/a/b") == 1, f"{api('GET', '/_test/echo/count')[1]}")
    check("the POST tool ran exactly once (no repeat after the retry)", echo_count("post") == 1, f"{echo_count('post')}")
    post = next((t for t in tools_ if t["tool_name"] == "save_note"), {})
    sent = ((post.get("result") or {}).get("data") or {}).get("body") or {}
    check("static fields win over the model's values", sent.get("source") == "smoke" and sent.get("note") == "hello", f"{sent}")
    get = next((t for t in tools_ if t["tool_name"] == "get_item"), {})
    check("path params are URL-encoded", "/get/a%2Fb" in ((get.get("request") or {}).get("url") or ""), f"{get.get('request')}")
    check("GET args become query params", (get.get("request") or {}).get("query", {}).get("limit") == "2")
    check("the tool's auth header is masked in the trace", (get.get("request") or {}).get("headers", {}).get("Authorization") == "••••••••")
    after = block_of(run["id"], "after")
    check("a downstream block resolved {{ agent_1.final.workflow_name }}",
          (((after.get("output") or {}).get("data") or {}).get("query") or {}).get("name") == "wf_a", f"{after.get('output')}")
    # Every block's output, resolved config and error, and so the agent's
    # trace. (The definition itself still holds the token, as for any HTTP
    # block: auth fields are part of a block's saved config.)
    run_detail = api("GET", f"/runs/{run['id']}")[1] or {}
    blob = json.dumps(rows) + json.dumps({k: v for k, v in run_detail.items() if k != "pipeline_snapshot"})
    check("the tool's credential appears nowhere in outputs, resolved configs or the trace", AGENT_SECRET not in blob)

    # max_iterations: a script that never finishes.
    loop_def = agent_def([{"tool_calls": [{"name": "get_item", "args": {"item": "loop"}}]}],
                         {"max_iterations": 2}, after=False)
    run = wait_run(start_run(new_pipe("agent_loop", loop_def)), timeout=60)
    check("a looping agent fails the run at max_iterations", status_of(run) == "failed", f"status {status_of(run)}")
    err = block_of(run["id"], "agent_1").get("error") or {} if run else {}
    check("...with stop_reason max_iterations and the trace kept",
          (err.get("detail") or {}).get("stop_reason") == "max_iterations" and len((err.get("detail") or {}).get("trace") or []) == 4
          and err.get("retryable") is False, f"{err}")

    # Test step on an agent: its tool calls are real.
    tdef = agent_def([{"tool_calls": [{"name": "save_note", "args": {"note": "from test step"}}]},
                      {"finish": {"workflow_name": "t", "error": "e"}}], after=False)
    tpid = new_pipe("agent_test_step", tdef)
    before = echo_count("post")
    status, data, err = api("POST", "/runs/test", {"pipeline_id": tpid, "block_id": "agent_1", "definition": tdef})
    trun = wait_run(data["run_id"]) if status == 202 else None
    check("test step on an agent succeeds and its tool call is real",
          status_of(trun) == "succeeded" and echo_count("post") == before + 1, f"{status} {err} {status_of(trun)}")
    status, _, _ = api("POST", "/runs/test", {"pipeline_id": tpid, "block_id": "post_tool", "definition": tdef})
    check("test step on a tool block is refused (use Test tool)", status == 400)

    # Test tool: one call, no agent.
    status, data, err = api("POST", "/tools/test", {"definition": tdef, "block_id": "get_tool", "args": {"item": "probe"}})
    check("POST /tools/test runs one call", status == 200 and (data or {}).get("ok") is True
          and (data or {}).get("request", {}).get("headers", {}).get("Authorization") == "••••••••", f"{status} {data or err}")
    check("...and the credential isn't in its response", AGENT_SECRET not in json.dumps(data))
    status, data, _ = api("POST", "/tools/test", {"definition": tdef, "block_id": "get_tool", "args": {"item": 5}})
    check("POST /tools/test rejects args that don't match the schema", status == 400 and problems_of(data))


def schedule_fire_checks(sched_id, started):
    section("16. Schedule trigger fires")
    deadline = started + 75  # "* * * * *" is due within 60s of activation
    runs = pipeline_runs(sched_id)
    while time.monotonic() < deadline and not runs:
        time.sleep(1)
        runs = pipeline_runs(sched_id)
    check("an active * * * * * schedule starts a run within a minute", len(runs) >= 1, f"{len(runs)} runs")
    if runs:
        run = wait_run(runs[-1]["id"])
        check("the scheduled run succeeds", status_of(run) == "succeeded", f"status {status_of(run)}")
        check("the run is marked trigger_type schedule", (run or {}).get("trigger_type") == "schedule")
        out = block_of(runs[-1]["id"], "sched").get("output") or {}
        check("schedule output has scheduled_for and fired_at", bool(out.get("scheduled_for")) and bool(out.get("fired_at")), f"{out}")
        trig = (api("GET", f"/pipelines/{sched_id}")[1] or {}).get("triggers", [{}])[0]
        check("next_run_at moved past the fired slot", (trig.get("next_run_at") or "") > (out.get("scheduled_for") or "~"), f"{trig}")
    api("PATCH", f"/pipelines/{sched_id}", {"is_active": False})
    check("deleting a scheduled workflow returns 204", api("DELETE", f"/pipelines/{sched_id}")[0] == 204)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # a crash is a failure, with the reason visible in the log
        print(f"\nSMOKE TEST CRASHED: {type(e).__name__}: {e}")
        sys.exit(1)
