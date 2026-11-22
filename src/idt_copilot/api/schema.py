"""Creates the live-run tables once per server process, safely when requests arrive at the same moment."""
from __future__ import annotations

import threading

import psycopg

LIVE_RUNS = """
CREATE TABLE IF NOT EXISTS live_runs (
    id             SERIAL PRIMARY KEY,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    participant_id TEXT NOT NULL,
    client_hash    TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'running',
    cost_usd       DOUBLE PRECISION,
    seconds        DOUBLE PRECISION
);
ALTER TABLE live_runs ADD COLUMN IF NOT EXISTS code_id INTEGER;
"""

ACCESS_CODES = """
CREATE TABLE IF NOT EXISTS access_codes (
    id            SERIAL PRIMARY KEY,
    code_hash     TEXT NOT NULL UNIQUE,
    label         TEXT NOT NULL,
    max_runs      INTEGER NOT NULL,
    max_cost_usd  DOUBLE PRECISION NOT NULL,
    runs_used     INTEGER NOT NULL DEFAULT 0,
    cost_used_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    expires_at    TIMESTAMPTZ,
    revoked_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at  TIMESTAMPTZ
);
"""

_lock = threading.Lock()
_ready: set[str] = set()


def ensure(conn, name: str, ddl: str) -> None:
    if name in _ready:
        return
    with _lock:
        if name in _ready:
            return
        try:
            # A transaction-scoped advisory lock serializes setup across server processes too.
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (name,))
                conn.execute(ddl)
        except (psycopg.errors.UniqueViolation, psycopg.errors.DuplicateTable, psycopg.errors.DuplicateObject):
            pass  # another request created it first
        _ready.add(name)


def ensure_live_runs(conn) -> None:
    ensure(conn, "live_runs", LIVE_RUNS)


def ensure_access_codes(conn) -> None:
    ensure(conn, "access_codes", ACCESS_CODES)


def forget() -> None:
    """For tests that drop the tables between cases."""
    _ready.clear()
