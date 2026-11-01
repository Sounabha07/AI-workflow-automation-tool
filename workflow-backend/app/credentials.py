"""
Saved credentials: secrets a client stores once and blocks reference by id.

Secrets are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256) under
CREDENTIALS_ENCRYPTION_KEY. Only the worker decrypts, right before a block
runs, and hands the plaintext to execute() as `credentials`, never inside
config, so it can't reach resolved_config, run outputs or logs. The API
accepts secrets but never returns them; it shows a short hint instead.
"""

import json
import os
from typing import Any
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from app.llm import PROVIDERS

ENCRYPTION_KEY_ENV = "CREDENTIALS_ENCRYPTION_KEY"

# type -> label and the secret fields it stores. Built from the LLM
# providers, so a new provider brings its credential type with it.
CREDENTIAL_TYPES: dict[str, dict[str, Any]] = {
    p.credential_type: {
        "label": p.credential_label,
        "fields": [{"name": "api_key", "label": "API key"}],
    }
    for p in PROVIDERS.values()
}


class CredentialsConfigError(RuntimeError):
    """The server can't encrypt/decrypt: CREDENTIALS_ENCRYPTION_KEY is missing
    or wrong. Rendered as a 500 by app.main's RuntimeError handler."""


class CredentialError(ValueError):
    """A block's credential can't be used (missing, wrong type, undecryptable)."""


def _fernet() -> Fernet:
    key = os.environ.get(ENCRYPTION_KEY_ENV, "").strip()
    if not key:
        raise CredentialsConfigError(
            f"Credentials are disabled: set {ENCRYPTION_KEY_ENV} for the API and the worker "
            "(see workflow-backend/.env.example)."
        )
    try:
        return Fernet(key.encode())
    except ValueError:
        raise CredentialsConfigError(
            f"{ENCRYPTION_KEY_ENV} is not a valid Fernet key (32 url-safe base64-encoded bytes)."
        ) from None


def generate_key() -> str:
    return Fernet.generate_key().decode()


def validate_secret(cred_type: str, data: Any) -> dict[str, str]:
    """The secret fields for a type, stripped; raises ValueError (400) if invalid."""
    spec = CREDENTIAL_TYPES.get(cred_type)
    if spec is None:
        raise ValueError(
            f"Unknown credential type '{cred_type}'. Use one of: {', '.join(CREDENTIAL_TYPES)}."
        )
    if not isinstance(data, dict):
        raise ValueError("'data' must be an object of secret fields.")
    out: dict[str, str] = {}
    for f in spec["fields"]:
        value = data.get(f["name"])
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{f['label']} is required.")
        out[f["name"]] = value.strip()
    return out


def encrypt(data: dict[str, str]) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt(token: str) -> dict[str, str]:
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken:
        raise CredentialError(
            f"the saved credential can't be decrypted; {ENCRYPTION_KEY_ENV} may have changed "
            "since it was saved. Re-enter the key on the Credentials page."
        ) from None


def hint_for(data: dict[str, str]) -> str:
    """Enough to recognize a key, never enough to use it."""
    secret = next(iter(data.values()), "")
    return f"…{secret[-4:]}" if len(secret) >= 12 else "…"


def credential_fields(schema: dict) -> list[dict]:
    return [f for f in schema.get("fields", []) if f.get("type") == "credential"]


async def load_block_credentials(conn, config: dict, schema: dict) -> dict[str, Any] | None:
    """Decrypted secrets for the block's credential field, plus "type" and
    "name"; None if the block has no credential selected. Raises
    CredentialError with a readable reason otherwise."""
    for field in credential_fields(schema):
        cred_id = config.get(field["name"])
        if cred_id in (None, ""):
            continue
        try:
            cred_uuid = UUID(str(cred_id))
        except ValueError:
            raise CredentialError(f"'{cred_id}' is not a credential id.") from None
        row = await conn.fetchrow(
            "SELECT name, type, secret_encrypted FROM credentials WHERE id = $1", cred_uuid
        )
        if row is None:
            raise CredentialError(
                "the selected credential no longer exists. Pick another one in the block's settings."
            )
        allowed = field.get("credential_types") or []
        if allowed and row["type"] not in allowed:
            raise CredentialError(
                f"credential '{row['name']}' is a {row['type']}, but this block needs one of: "
                f"{', '.join(allowed)}."
            )
        return {**decrypt(row["secret_encrypted"]), "type": row["type"], "name": row["name"]}
    return None
