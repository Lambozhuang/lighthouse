"""Apply supabase/migrations/*.sql in filename order, once each.

    python -m lighthouse.migrate

Plain SQL files and a bookkeeping table; no migration framework. The files are also valid input
for `supabase db push` if the Supabase CLI is used instead.
"""

import asyncio
import os
import sys
from pathlib import Path

import psycopg

from lighthouse.config import get_settings

MIGRATIONS_DIR = Path(os.environ.get("LIGHTHOUSE_MIGRATIONS_DIR", "supabase/migrations"))


async def migrate(database_url: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Returns the names of the migrations applied by this call."""
    files = {path.name: path.read_text() for path in sorted(directory.glob("*.sql"))}  # noqa: ASYNC240
    applied_now: list[str] = []
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as conn:
        await conn.execute("create schema if not exists lighthouse")
        await conn.execute(
            "create table if not exists lighthouse.schema_migrations "
            "(name text primary key, applied_at timestamptz not null default now())"
        )
        # One migrator at a time (API and worker may start together).
        await conn.execute("select pg_advisory_lock(hashtext('lighthouse.migrate'))")
        cur = await conn.execute("select name from lighthouse.schema_migrations")
        done = {row[0] for row in await cur.fetchall()}
        for name, sql in files.items():
            if name in done:
                continue
            async with conn.transaction():
                await conn.execute(sql)  # pyright: ignore[reportArgumentType, reportCallIssue]
                await conn.execute("insert into lighthouse.schema_migrations (name) values (%s)", [name])
            applied_now.append(name)
    return applied_now


if __name__ == "__main__":
    names = asyncio.run(migrate(get_settings().database_url))
    print("applied: " + (", ".join(names) or "nothing, already up to date"), file=sys.stderr)
