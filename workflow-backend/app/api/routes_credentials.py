"""
/credentials — save, list, rename/replace and delete secrets.

Write-only for secrets: POST and PATCH accept them, no route returns them.
"""

from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException

from app.api.models import (
    CreateCredentialRequest,
    CredentialResponse,
    CredentialTypeResponse,
    UpdateCredentialRequest,
)
from app.credentials import CREDENTIAL_TYPES, encrypt, hint_for, validate_secret
from app.errors import NotFoundError
from db import get_connection

router = APIRouter()

_COLUMNS = "id, name, type, hint, created_at, updated_at"


def _response(row) -> CredentialResponse:
    d = dict(row)
    return CredentialResponse(**d, type_label=CREDENTIAL_TYPES.get(d["type"], {}).get("label", d["type"]))


def _clean_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Credential name can't be empty.")
    return name


def _name_taken(name: str) -> HTTPException:
    return HTTPException(409, f"A credential named '{name}' already exists.")


@router.get("/types", response_model=list[CredentialTypeResponse])
async def list_credential_types() -> list[CredentialTypeResponse]:
    return [CredentialTypeResponse(type=t, **spec) for t, spec in CREDENTIAL_TYPES.items()]


@router.get("", response_model=list[CredentialResponse])
async def list_credentials() -> list[CredentialResponse]:
    conn = await get_connection()
    try:
        rows = await conn.fetch(f"SELECT {_COLUMNS} FROM credentials ORDER BY name")
        return [_response(r) for r in rows]
    finally:
        await conn.close()


@router.post("", status_code=201, response_model=CredentialResponse)
async def create_credential(body: CreateCredentialRequest) -> CredentialResponse:
    name = _clean_name(body.name)
    data = validate_secret(body.type, body.data)
    token = encrypt(data)
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            f"""
            INSERT INTO credentials (name, type, secret_encrypted, hint)
            VALUES ($1, $2, $3, $4)
            RETURNING {_COLUMNS}
            """,
            name, body.type, token, hint_for(data),
        )
        return _response(row)
    except asyncpg.UniqueViolationError:
        raise _name_taken(name) from None
    finally:
        await conn.close()


@router.patch("/{credential_id}", response_model=CredentialResponse)
async def update_credential(credential_id: UUID, body: UpdateCredentialRequest) -> CredentialResponse:
    if body.name is None and body.data is None:
        raise ValueError("Provide a new 'name', new secret 'data', or both.")
    conn = await get_connection()
    try:
        current = await conn.fetchrow("SELECT type FROM credentials WHERE id = $1", credential_id)
        if current is None:
            raise NotFoundError(f"Credential {credential_id} not found")

        sets, params = ["updated_at = NOW()"], []
        if body.name is not None:
            params.append(_clean_name(body.name))
            sets.append(f"name = ${len(params)}")
        if body.data is not None:
            data = validate_secret(current["type"], body.data)
            params += [encrypt(data), hint_for(data)]
            sets += [f"secret_encrypted = ${len(params) - 1}", f"hint = ${len(params)}"]
        params.append(credential_id)
        row = await conn.fetchrow(
            f"UPDATE credentials SET {', '.join(sets)} WHERE id = ${len(params)} RETURNING {_COLUMNS}",
            *params,
        )
        return _response(row)
    except asyncpg.UniqueViolationError:
        raise _name_taken(body.name or "") from None
    finally:
        await conn.close()


@router.delete("/{credential_id}", status_code=204)
async def delete_credential(credential_id: UUID) -> None:
    conn = await get_connection()
    try:
        async with conn.transaction():
            exists = await conn.fetchval("SELECT 1 FROM credentials WHERE id = $1 FOR UPDATE", credential_id)
            if not exists:
                raise NotFoundError(f"Credential {credential_id} not found")
            # Ids are UUIDs, so a text match on the definition can't hit anything else.
            users = await conn.fetch(
                "SELECT name FROM pipelines WHERE definition::text LIKE '%' || $1 || '%' ORDER BY name",
                str(credential_id),
            )
            if users:
                names = ", ".join(f"'{u['name']}'" for u in users)
                raise HTTPException(
                    409, f"This credential is used by {names}. Pick another credential there first."
                )
            await conn.execute("DELETE FROM credentials WHERE id = $1", credential_id)
    finally:
        await conn.close()
