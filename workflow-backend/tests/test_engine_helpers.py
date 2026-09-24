import pytest

from blocks.base import FatalError, RetryableError
from blocks.http_request import MAX_ERROR_BODY_CHARS, HttpRequestBlock
from engine import MASK, _outgoing_edges, mask_sensitive
from retry import compute_backoff_seconds


def test_outgoing_edges_for_plain_and_switch_blocks():
    assert _outgoing_edges({"next": ["a", "b"]}) == [("a", None), ("b", None)]
    assert _outgoing_edges({"next": {"big": ["a"], "fallback": ["b", "c"]}}) == [
        ("a", "big"), ("b", "fallback"), ("c", "fallback"),
    ]
    assert _outgoing_edges({}) == []


def test_mask_sensitive_hides_only_sensitive_non_empty_fields():
    cfg = {"url": "https://x", "bearer_token": "s3cret", "basic_password": "", "authentication": "bearer"}
    masked = mask_sensitive(cfg, HttpRequestBlock.schema)
    assert masked["bearer_token"] == MASK
    assert masked["basic_password"] == ""  # nothing to hide
    assert masked["url"] == "https://x"
    assert cfg["bearer_token"] == "s3cret"  # original untouched


@pytest.mark.parametrize("status,error", [(429, RetryableError), (500, RetryableError), (503, RetryableError), (404, FatalError), (400, FatalError)])
def test_http_status_classification(status, error):
    with pytest.raises(error):
        HttpRequestBlock._raise_for_status(status, b"body")


def test_http_error_body_kept_up_to_limit_then_truncated():
    short = "x" * 500
    with pytest.raises(FatalError) as e:
        HttpRequestBlock._raise_for_status(400, short.encode())
    assert short in str(e.value) and "truncated" not in str(e.value)

    with pytest.raises(FatalError) as e:
        HttpRequestBlock._raise_for_status(400, ("y" * (MAX_ERROR_BODY_CHARS + 50)).encode())
    assert ("y" * MAX_ERROR_BODY_CHARS + "… (truncated)") in str(e.value)


def test_backoff_stays_within_exponential_cap():
    for attempt in range(8):
        delay = compute_backoff_seconds(attempt, base=1.0, cap=10.0)
        assert 0 <= delay <= min(10.0, 2 ** attempt)
