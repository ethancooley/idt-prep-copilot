"""Read-only access to a participant's synthetic chart.

The MCP server and, later, the agent's tests both go through this class, so every query lives in one
place. Every note it returns carries its id, which is what the brief cites.
"""
from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row

DEFAULT_DATABASE_URL = "postgresql://idt:idt@localhost:5432/idt"
KG_TO_LB = 2.20462
ELEVATED_SYSTOLIC, ELEVATED_DIASTOLIC = 140, 90


class NotFound(LookupError):
    pass


def _iso(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _iso(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_iso(v) for v in value]
    return value


def _parse_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f"Dates must be YYYY-MM-DD, got {value!r}") from e


class ChartRepository:
    def __init__(self, database_url: str | None = None, use_embeddings: bool = True):
        self.database_url = database_url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
        self._conn: psycopg.Connection | None = None
        self._use_embeddings = use_embeddings
        self._embedder = None

    # ------------------------------------------------------------ plumbing

    @property
    def conn(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            if not self.database_url.startswith(("postgresql://", "postgres://")):
                # Never echo the value: a mistyped setting is often a password.
                raise RuntimeError("DATABASE_URL is not a postgresql:// connection string.")
            try:
                self._conn = psycopg.connect(self.database_url, autocommit=True, row_factory=dict_row)
            except psycopg.ProgrammingError:
                # psycopg's parse errors quote part of the string, which can include the password.
                raise RuntimeError("DATABASE_URL could not be parsed as a connection string.") from None
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        return [_iso(r) for r in self.conn.execute(sql, params).fetchall()]

    def _window(self, participant_id: str) -> dict:
        row = self.conn.execute(
            "SELECT window_start, review_date FROM participants WHERE id = %s", (participant_id,)).fetchone()
        if row is None:
            raise NotFound(f"No participant with id {participant_id!r}. Use list_participants to see valid ids.")
        return row

    def _since(self, participant_id: str, since: str | date | None) -> date:
        return _parse_date(since) or self._window(participant_id)["window_start"]

    # ------------------------------------------------------------ tools

    def list_participants(self) -> list[dict]:
        return self._all("""
            SELECT p.id, p.first_name || ' ' || p.last_name AS name,
                   date_part('year', age(p.review_date, p.birth_date))::int AS age,
                   p.review_date, p.window_start,
                   count(n.id) FILTER (WHERE n.note_date >= p.window_start) AS notes_since_last_review
            FROM participants p LEFT JOIN notes n ON n.participant_id = p.id
            GROUP BY p.id ORDER BY p.last_name, p.first_name""")

    def get_participant_summary(self, participant_id: str) -> dict:
        p = self.conn.execute("""
            SELECT id, first_name, last_name, sex, city, birth_date,
                   date_part('year', age(review_date, birth_date))::int AS age,
                   enrollment_date, review_date, window_start
            FROM participants WHERE id = %s""", (participant_id,)).fetchone()
        if p is None:
            raise NotFound(f"No participant with id {participant_id!r}. Use list_participants to see valid ids.")
        summary = _iso(dict(p))
        summary["conditions"] = self._all(
            "SELECT description, onset FROM conditions WHERE participant_id = %s ORDER BY onset", (participant_id,))
        summary["active_medications"] = self._all("""
            SELECT description, start_date, note FROM medications
            WHERE participant_id = %s AND (stop_date IS NULL OR stop_date > %s)
            ORDER BY description""", (participant_id, p["review_date"]))
        summary["allergies"] = self._all(
            "SELECT description, reaction FROM allergies WHERE participant_id = %s", (participant_id,))
        return summary

    def get_notes(self, participant_id: str, start_date: str | None = None, end_date: str | None = None,
                  author_role: str | None = None, limit: int = 100) -> list[dict]:
        window = self._window(participant_id)
        start = _parse_date(start_date) or window["window_start"]
        end = _parse_date(end_date) or window["review_date"]
        sql = """SELECT id, note_date, author_role, note_type, text FROM notes
                 WHERE participant_id = %s AND note_date >= %s AND note_date <= %s"""
        params: list[Any] = [participant_id, start, end]
        if author_role:
            sql += " AND author_role ILIKE %s"
            params.append(f"%{author_role}%")
        sql += " ORDER BY note_date, id LIMIT %s"
        params.append(max(1, min(limit, 200)))
        return self._all(sql, tuple(params))

    def get_note(self, note_id: str) -> dict:
        rows = self._all(
            "SELECT id, participant_id, note_date, author_role, note_type, text FROM notes WHERE id = %s", (note_id,))
        if not rows:
            raise NotFound(f"No note with id {note_id!r}.")
        return rows[0]

    def search_notes(self, participant_id: str, query: str, limit: int = 5, since: str | None = None) -> dict:
        self._window(participant_id)
        start = _parse_date(since)
        limit = max(1, min(limit, 20))
        embedder = self._get_embedder()
        if embedder is not None and self._has_embeddings(participant_id):
            from pgvector.psycopg import register_vector
            register_vector(self.conn)
            vector = next(iter(embedder.query_embed([query])))
            rows = self._all(f"""
                SELECT id, note_date, author_role, note_type, text,
                       round((1 - (embedding <=> %s))::numeric, 3)::float AS score
                FROM notes WHERE participant_id = %s AND embedding IS NOT NULL
                {"AND note_date >= %s" if start else ""}
                ORDER BY embedding <=> %s LIMIT %s""",
                tuple(x for x in (vector, participant_id, start, vector, limit) if x is not None))
            return {"mode": "semantic", "results": rows}
        terms = " or ".join(re.findall(r"[A-Za-z0-9]+", query)) or query
        rows = self._all(f"""
            SELECT id, note_date, author_role, note_type, text,
                   round(ts_rank(to_tsvector('english', text), websearch_to_tsquery('english', %s))::numeric, 3)::float AS score
            FROM notes WHERE participant_id = %s
              AND to_tsvector('english', text) @@ websearch_to_tsquery('english', %s)
              {"AND note_date >= %s" if start else ""}
            ORDER BY score DESC, note_date DESC LIMIT %s""",
            tuple(x for x in (terms, participant_id, terms, start, limit) if x is not None))
        return {"mode": "keyword", "results": rows}

    def get_vitals(self, participant_id: str, kind: str = "all", since: str | None = None) -> dict:
        start = self._since(participant_id, since)
        out: dict[str, Any] = {"since": start.isoformat()}
        if kind in ("all", "weight"):
            weights = self._all("""
                SELECT obs_date, value_num AS kg FROM observations
                WHERE participant_id = %s AND description = 'Body Weight' AND obs_date >= %s
                ORDER BY obs_date""", (participant_id, start))
            for w in weights:
                w["lb"] = round(w["kg"] * KG_TO_LB, 1)
            out["weight"] = {"readings": weights}
            if len(weights) >= 2:
                first, last = weights[0], weights[-1]
                change = last["kg"] - first["kg"]
                out["weight"]["change"] = {
                    "from": first["obs_date"], "to": last["obs_date"],
                    "kg": round(change, 1), "lb": round(change * KG_TO_LB, 1),
                    "percent": round(100 * change / first["kg"], 1),
                }
        if kind in ("all", "blood_pressure"):
            rows = self._all("""
                SELECT obs_date,
                       max(value_num) FILTER (WHERE description = 'Systolic Blood Pressure') AS systolic,
                       max(value_num) FILTER (WHERE description = 'Diastolic Blood Pressure') AS diastolic
                FROM observations
                WHERE participant_id = %s AND obs_date >= %s
                  AND description IN ('Systolic Blood Pressure', 'Diastolic Blood Pressure')
                GROUP BY obs_date ORDER BY obs_date""", (participant_id, start))
            readings = [{"obs_date": r["obs_date"], "systolic": int(r["systolic"]), "diastolic": int(r["diastolic"])}
                        for r in rows if r["systolic"] is not None and r["diastolic"] is not None]
            elevated = [r for r in readings
                        if r["systolic"] >= ELEVATED_SYSTOLIC or r["diastolic"] >= ELEVATED_DIASTOLIC]
            out["blood_pressure"] = {"readings": readings, "elevated_count": len(elevated),
                                     "elevated_threshold": f"{ELEVATED_SYSTOLIC}/{ELEVATED_DIASTOLIC}"}
        if kind not in ("all", "weight", "blood_pressure"):
            raise ValueError("kind must be 'all', 'weight', or 'blood_pressure'")
        return out

    def get_encounters(self, participant_id: str, since: str | None = None) -> list[dict]:
        start = self._since(participant_id, since)
        return self._all("""
            SELECT id, start_date, encounter_class, description, reason FROM encounters
            WHERE participant_id = %s AND start_date >= %s ORDER BY start_date""", (participant_id, start))

    def get_medication_changes(self, participant_id: str, since: str | None = None) -> dict:
        start = self._since(participant_id, since)
        started = self._all("""
            SELECT description, start_date, stop_date, note FROM medications
            WHERE participant_id = %s AND start_date >= %s ORDER BY start_date""", (participant_id, start))
        stopped = self._all("""
            SELECT description, start_date, stop_date, note FROM medications
            WHERE participant_id = %s AND stop_date >= %s AND start_date < %s ORDER BY stop_date""",
            (participant_id, start, start))
        return {"since": start.isoformat(), "started": started, "stopped": stopped}

    def get_immunizations(self, participant_id: str) -> dict:
        review = self._window(participant_id)["review_date"]
        season_start = date(review.year if review.month >= 8 else review.year - 1, 8, 1)
        records = self._all("""
            SELECT imm_date, description FROM immunizations
            WHERE participant_id = %s ORDER BY imm_date DESC""", (participant_id,))
        flu_this_season = any(r["imm_date"] >= season_start.isoformat() and "influenza" in r["description"].lower()
                              for r in records)
        return {"records_last_two_years": records, "flu_season_start": season_start.isoformat(),
                "flu_vaccine_this_season": flu_this_season}

    # ------------------------------------------------------------ embeddings

    def _has_embeddings(self, participant_id: str) -> bool:
        row = self.conn.execute(
            "SELECT EXISTS (SELECT 1 FROM notes WHERE participant_id = %s AND embedding IS NOT NULL) AS e",
            (participant_id,)).fetchone()
        return bool(row["e"])

    def _get_embedder(self):
        if not self._use_embeddings or os.environ.get("IDT_DISABLE_EMBEDDINGS") == "1":
            return None
        if self._embedder is None:
            try:
                from fastembed import TextEmbedding

                from idt_copilot.db.load import EMBED_MODEL
                self._embedder = TextEmbedding(EMBED_MODEL)
            except Exception:  # model or package unavailable: fall back to keyword search
                self._use_embeddings = False
                return None
        return self._embedder
