"""Credential encryption and lookup. A fake connection stands in for Postgres."""

import uuid

import pytest
from cryptography.fernet import Fernet

from app.credentials import (
    CredentialError,
    CredentialsConfigError,
    decrypt,
    encrypt,
    hint_for,
    load_block_credentials,
    validate_secret,
)
from blocks.llm import LLMBlock

KEY = "AIza-client-own-key-0123456789"


@pytest.fixture(autouse=True)
def enc_key(monkeypatch):
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode())


class FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    async def fetchrow(self, sql, *args):
        self.queries.append(args)
        return self.rows.get(args[0])


def test_round_trip_and_ciphertext_hides_the_secret():
    token = encrypt({"api_key": KEY})
    assert KEY not in token
    assert decrypt(token) == {"api_key": KEY}


def test_missing_encryption_key_is_a_clear_server_error(monkeypatch):
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEY")
    with pytest.raises(CredentialsConfigError, match="CREDENTIALS_ENCRYPTION_KEY"):
        encrypt({"api_key": KEY})


def test_invalid_encryption_key(monkeypatch):
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", "too-short")
    with pytest.raises(CredentialsConfigError, match="not a valid Fernet key"):
        encrypt({"api_key": KEY})


def test_rotated_encryption_key_gives_a_readable_error(monkeypatch):
    token = encrypt({"api_key": KEY})
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(CredentialError, match="can't be decrypted"):
        decrypt(token)


def test_validate_secret():
    assert validate_secret("gemini_api_key", {"api_key": f"  {KEY} "}) == {"api_key": KEY}
    with pytest.raises(ValueError, match="Unknown credential type"):
        validate_secret("nope", {"api_key": KEY})
    with pytest.raises(ValueError, match="API key is required"):
        validate_secret("gemini_api_key", {"api_key": "  "})
    with pytest.raises(ValueError, match="must be an object"):
        validate_secret("gemini_api_key", "AIza")


def test_hint_shows_only_the_last_four():
    assert hint_for({"api_key": KEY}) == "…6789"
    assert hint_for({"api_key": "short"}) == "…"


async def test_load_block_credentials():
    cid = uuid.uuid4()
    conn = FakeConn({cid: {"name": "Acme", "type": "gemini_api_key", "secret_encrypted": encrypt({"api_key": KEY})}})
    creds = await load_block_credentials(conn, {"credential": str(cid)}, LLMBlock.schema)
    assert creds == {"api_key": KEY, "type": "gemini_api_key", "name": "Acme"}


async def test_no_credential_selected_returns_none():
    conn = FakeConn({})
    assert await load_block_credentials(conn, {"credential": ""}, LLMBlock.schema) is None
    assert conn.queries == []


async def test_deleted_credential():
    with pytest.raises(CredentialError, match="no longer exists"):
        await load_block_credentials(FakeConn({}), {"credential": str(uuid.uuid4())}, LLMBlock.schema)


async def test_wrong_credential_type():
    cid = uuid.uuid4()
    conn = FakeConn({cid: {"name": "Other", "type": "openai_api_key", "secret_encrypted": encrypt({"api_key": KEY})}})
    with pytest.raises(CredentialError, match="needs one of: gemini_api_key"):
        await load_block_credentials(conn, {"credential": str(cid)}, LLMBlock.schema)


async def test_malformed_id():
    with pytest.raises(CredentialError, match="not a credential id"):
        await load_block_credentials(FakeConn({}), {"credential": "abc"}, LLMBlock.schema)
