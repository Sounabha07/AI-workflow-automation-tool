"""HTTP Request block: request building and response parsing, with urlopen
replaced so nothing touches the network."""

import io
import urllib.error

import pytest

import blocks.http_request as http
from blocks.base import FatalError, RetryableError


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def sent(monkeypatch):
    """Captures each request; answers with sent.response (default JSON {})."""
    calls = []

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(req)
        r = calls.response if hasattr(calls, "response") else None
        if isinstance(r, Exception):
            raise r
        return r or FakeResponse(b"{}", headers={"Content-Type": "application/json"})

    calls = type("Calls", (list,), {})()
    monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
    return calls


async def run(config):
    return await http.HttpRequestBlock().execute({"method": "GET", **config}, {})


async def test_spaces_and_non_ascii_in_the_url_are_encoded(sent):
    await run({"url": "http://api.test/find?name=Live demo&city=Zürich&x=%2F"})
    assert sent[0].full_url == "http://api.test/find?name=Live%20demo&city=Z%C3%BCrich&x=%2F"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x.test/a", "api.test/x"])
async def test_only_http_urls_are_allowed(sent, url):
    with pytest.raises(FatalError, match="http:// or https://"):
        await run({"url": url})
    assert sent == []


async def test_bad_timeout_is_a_clear_fatal_error(sent):
    with pytest.raises(FatalError, match="timeout_seconds"):
        await run({"url": "http://api.test/", "timeout_seconds": "soon"})


async def test_malformed_key_value_entries_are_skipped(sent):
    await run({"url": "http://api.test/", "send_headers": True, "headers": [None, {"key": "X-A", "value": "1"}, "x"],
               "send_query_params": True, "query_params": None})
    assert sent[0].get_header("X-a") == "1" and sent[0].full_url == "http://api.test/"


@pytest.mark.parametrize("ctype", ["application/json; charset=utf-8", "application/problem+json", "APPLICATION/JSON"])
async def test_json_content_types_are_parsed(sent, ctype):
    sent.response = FakeResponse(b'{"a": 1}', headers={"content-type": ctype})
    assert (await run({"url": "http://api.test/"}))["data"] == {"a": 1}


async def test_undecodable_json_body_falls_back_to_text(sent):
    sent.response = FakeResponse(b"\xff\xfe", headers={"Content-Type": "application/json"})
    out = await run({"url": "http://api.test/"})
    assert isinstance(out["data"], str)


async def test_status_errors_carry_status_and_body(sent):
    sent.response = urllib.error.HTTPError("http://api.test/", 404, "nf", {}, io.BytesIO(b"missing"))
    with pytest.raises(FatalError) as e:
        await run({"url": "http://api.test/"})
    assert e.value.status == 404 and e.value.body == "missing"
    sent.response = urllib.error.HTTPError("http://api.test/", 503, "x", {}, io.BytesIO(b""))
    with pytest.raises(RetryableError):
        await run({"url": "http://api.test/"})


async def test_read_timeout_is_retryable(sent):
    sent.response = TimeoutError("timed out")
    with pytest.raises(RetryableError, match="network error"):
        await run({"url": "http://api.test/"})
