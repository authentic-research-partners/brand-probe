"""All database access uses this context manager."""

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from collections.abc import Iterator
from brandprobe.exceptions import BrandProbeError


@contextmanager
def get_db(root: Path) -> Iterator[sqlite3.Connection]:
    folder = root / ".brandprobe"
    folder.mkdir(exist_ok=True, parents=True)
    conn = sqlite3.connect(folder / "history.db", timeout=5)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise BrandProbeError(
                "Unsupported history schema; use the BrandProbe version that created this database."
            )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS audits (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS one_continuation ON audits(json_extract(body, '$.plan.parent_audit_id')) WHERE json_extract(body, '$.plan.parent_audit_id') IS NOT NULL"
        )
        conn.execute("PRAGMA user_version=1")
        conn.commit()
        yield conn
    finally:
        conn.close()
