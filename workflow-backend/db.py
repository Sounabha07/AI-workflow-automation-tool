import os

import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://dag_user:dag_password@localhost:5432/dag_db"
)

_pool: asyncpg.Pool | None = None


async def get_connection() -> asyncpg.Connection:
    return await asyncpg.connect(dsn=DATABASE_URL)


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=DATABASE_URL)
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def apply_schema() -> None:
    conn = await get_connection()
    try:
        with open("schema.sql") as f:
            await conn.execute(f.read())
    finally:
        await conn.close()
