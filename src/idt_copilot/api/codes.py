"""Personal access codes for live runs: one per person, each with its own limits.

A code looks like IDT-7K4M-Q9XP. Only its SHA-256 fingerprint is stored, so the database never holds a
usable code; the code itself is shown once, when it is created in the admin console.

Each code has a run limit, a spending limit, and an optional expiry. A run is reserved atomically before
the agent starts (so two runs at once can't both slip under a limit), and its real cost is added when it
finishes. A run only starts if the code has at least MIN_RUN_BUDGET of spending left, so a code can't go
meaningfully over its spending limit.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from idt_copilot.api import schema

ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/O or 1/I/L, so codes read cleanly
MIN_RUN_BUDGET = 0.10  # a brief costs about $0.04; this leaves headroom for a long run

PUBLIC_FIELDS = ("id", "label", "max_runs", "max_cost_usd", "runs_used", "cost_used_usd", "expires_at",
                 "revoked_at", "created_at", "last_used_at")


@dataclass
class Reserved:
    code_id: int
    label: str
    runs_left: int
    budget_left: float


class CodeRejected(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def normalize(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def fingerprint(code: str) -> str:
    return hashlib.sha256(normalize(code).encode()).hexdigest()


def new_code() -> str:
    chars = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return f"IDT-{chars[:4]}-{chars[4:]}"


def ensure_schema(conn) -> None:
    schema.ensure_access_codes(conn)


def _public(row: dict) -> dict:
    out = {k: row[k] for k in PUBLIC_FIELDS}
    for k in ("expires_at", "revoked_at", "created_at", "last_used_at"):
        out[k] = out[k].isoformat() if out[k] else None
    now = datetime.now(timezone.utc)
    if row["revoked_at"]:
        state = "revoked"
    elif row["expires_at"] and row["expires_at"] <= now:
        state = "expired"
    elif row["runs_used"] >= row["max_runs"] or row["max_cost_usd"] - row["cost_used_usd"] < MIN_RUN_BUDGET:
        state = "used_up"
    else:
        state = "active"
    out["state"] = state
    return out


def create_code(conn, label: str, max_runs: int, max_cost_usd: float, expires_in_days: int | None) -> tuple[str, dict]:
    """Returns (the code, its public record). The code is never stored or shown again."""
    label = label.strip()[:80]
    if not label:
        raise ValueError("Give the code a name, such as who it's for.")
    if not 1 <= max_runs <= 100:
        raise ValueError("Runs must be between 1 and 100.")
    if not MIN_RUN_BUDGET <= max_cost_usd <= 50:
        raise ValueError(f"Spending limit must be between ${MIN_RUN_BUDGET:.2f} and $50.")
    expires = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)) if expires_in_days else None
    ensure_schema(conn)
    for _ in range(5):  # a collision is astronomically unlikely, but never silently reuse a code
        code = new_code()
        row = conn.execute(
            """INSERT INTO access_codes (code_hash, label, max_runs, max_cost_usd, expires_at)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (code_hash) DO NOTHING RETURNING *""",
            (fingerprint(code), label, max_runs, max_cost_usd, expires)).fetchone()
        if row:
            return code, _public(row)
    raise RuntimeError("Could not generate a unique code.")


def list_codes(conn) -> list[dict]:
    ensure_schema(conn)
    return [_public(r) for r in conn.execute("SELECT * FROM access_codes ORDER BY created_at DESC").fetchall()]


def update_code(conn, code_id: int, max_runs: int, max_cost_usd: float, expires_in_days: int | None,
                keep_expiry: bool) -> dict | None:
    """Change a code's limits: more runs, more spending, a later expiry. Turned-off codes stay off."""
    ensure_schema(conn)
    current = conn.execute("SELECT * FROM access_codes WHERE id = %s", (code_id,)).fetchone()
    if not current:
        return None
    if current["revoked_at"]:
        raise CodeRejected(409, "This code was turned off, and turned-off codes stay off. Make a new code instead.")
    if not 1 <= max_runs <= 100:
        raise ValueError("Runs must be between 1 and 100.")
    if not MIN_RUN_BUDGET <= max_cost_usd <= 50:
        raise ValueError(f"Spending limit must be between ${MIN_RUN_BUDGET:.2f} and $50.")
    if keep_expiry:
        expires = current["expires_at"]
    else:
        expires = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)) if expires_in_days else None
    row = conn.execute(
        "UPDATE access_codes SET max_runs = %s, max_cost_usd = %s, expires_at = %s WHERE id = %s RETURNING *",
        (max_runs, max_cost_usd, expires, code_id)).fetchone()
    return _public(row)


def revoke_code(conn, code_id: int) -> dict | None:
    ensure_schema(conn)
    row = conn.execute("UPDATE access_codes SET revoked_at = COALESCE(revoked_at, now()) WHERE id = %s RETURNING *",
                       (code_id,)).fetchone()
    return _public(row) if row else None


def reserve_run(conn, code: str) -> Reserved | None:
    """Reserve one run on a personal code. None if the code doesn't exist; CodeRejected if it can't be used."""
    ensure_schema(conn)
    row = conn.execute(
        """UPDATE access_codes SET runs_used = runs_used + 1, last_used_at = now()
           WHERE code_hash = %s AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())
             AND runs_used < max_runs AND max_cost_usd - cost_used_usd >= %s
           RETURNING *""", (fingerprint(code), MIN_RUN_BUDGET)).fetchone()
    if row:
        return Reserved(row["id"], row["label"], row["max_runs"] - row["runs_used"],
                        round(row["max_cost_usd"] - row["cost_used_usd"], 4))
    existing = conn.execute("SELECT * FROM access_codes WHERE code_hash = %s", (fingerprint(code),)).fetchone()
    if not existing:
        return None
    state = _public(existing)["state"]
    if state == "revoked":
        raise CodeRejected(403, "This access code has been turned off.")
    if state == "expired":
        raise CodeRejected(403, "This access code has expired.")
    raise CodeRejected(429, "This access code has used all of its live runs. Saved briefs are still available.")


def release_run(conn, code_id: int) -> None:
    """Give a reserved run back (the run was refused before the agent started)."""
    conn.execute("UPDATE access_codes SET runs_used = GREATEST(runs_used - 1, 0) WHERE id = %s", (code_id,))


def charge(conn, code_id: int, cost_usd: float) -> None:
    conn.execute("UPDATE access_codes SET cost_used_usd = cost_used_usd + %s WHERE id = %s", (cost_usd, code_id))
