import hashlib
import hmac

from blocks.webhook_trigger import build_payload, expected_signature, parse_body, verify_signature

SECRET = "s3cret"
BODY = b'{"repo": "octo/cat"}'


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_accepted():
    assert verify_signature(SECRET, BODY, sign(BODY))
    assert expected_signature(SECRET, BODY) == sign(BODY)


def test_tampered_body_rejected():
    assert not verify_signature(SECRET, b'{"repo": "evil/cat"}', sign(BODY))


def test_missing_or_malformed_header_rejected():
    assert not verify_signature(SECRET, BODY, None)
    assert not verify_signature(SECRET, BODY, "")
    assert not verify_signature(SECRET, BODY, sign(BODY)[len("sha256="):])  # no prefix
    assert not verify_signature(SECRET, BODY, sign(BODY, "other-secret"))
    assert not verify_signature(SECRET, BODY, "sha256=ünïcode")


def test_body_parsing():
    assert parse_body(b'{"a": 1}') == {"a": 1}
    assert parse_body(b"[1, 2]") == [1, 2]
    assert parse_body(b"") is None
    assert parse_body(b"  \n") is None
    assert parse_body(b"name=x&y=2") == "name=x&y=2"


def test_payload_drops_credentials_and_signature_header():
    payload = build_payload(
        "post",
        BODY,
        {"page": "2"},
        {"Authorization": "Bearer x", "Cookie": "a=b", "X-Hub-Signature-256": "sha256=..",
         "X-GitHub-Event": "push", "Content-Type": "application/json"},
    )
    assert payload == {
        "method": "POST",
        "body": {"repo": "octo/cat"},
        "query": {"page": "2"},
        "headers": {"x-github-event": "push", "content-type": "application/json"},
    }


def test_custom_signature_header_is_the_one_dropped():
    payload = build_payload("POST", b"", {}, {"X-Sig": "abc", "X-Hub-Signature-256": "kept"}, "X-Sig")
    assert payload["headers"] == {"x-hub-signature-256": "kept"}
