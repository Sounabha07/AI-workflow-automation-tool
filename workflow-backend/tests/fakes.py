"""A scripted stand-in for an asyncpg connection, for engine tests that
need to see which statements ran without a real database."""

from contextlib import asynccontextmanager


class ScriptedConn:
    """`responses` maps a SQL fragment to the value returned by any
    fetch/fetchrow/fetchval/execute whose query contains it (first match
    wins; a callable is called with the args). Unmatched queries return None,
    or [] for fetch. Every call is recorded in `calls` as (query, args)."""

    def __init__(self, responses: dict | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, tuple]] = []
        self.closed = False

    def _answer(self, query, args, default):
        self.calls.append((query, args))
        for fragment, value in self.responses.items():
            if fragment in query:
                return value(*args) if callable(value) else value
        return default

    async def fetch(self, query, *args):
        return self._answer(query, args, [])

    async def fetchrow(self, query, *args):
        return self._answer(query, args, None)

    async def fetchval(self, query, *args):
        return self._answer(query, args, None)

    async def execute(self, query, *args):
        return self._answer(query, args, "OK")

    @asynccontextmanager
    async def transaction(self):
        yield

    async def close(self):
        self.closed = True

    def ran(self, fragment: str) -> bool:
        return any(fragment in q for q, _ in self.calls)
