"""Load the synthetic cohort into Postgres (with pgvector).

    docker compose up -d
    python -m idt_copilot.db.load              # structured data and notes
    python -m idt_copilot.db.load --embed      # also embed notes for semantic search
"""
from __future__ import annotations

import argparse
import os
from importlib import resources
from pathlib import Path

import psycopg

from idt_copilot.models import Participant

EMBED_MODEL = "BAAI/bge-small-en-v1.5"  # 384 dimensions, runs locally, no API cost


def load_cohort(cohort_dir: Path) -> list[Participant]:
    return [Participant.model_validate_json(p.read_text())
            for p in sorted(cohort_dir.glob("*.json")) if p.name != "index.json"]


def create_schema(conn: psycopg.Connection) -> None:
    conn.execute(resources.files("idt_copilot.db").joinpath("schema.sql").read_text())


def insert_participant(cur: psycopg.Cursor, p: Participant) -> None:
    cur.execute(
        "INSERT INTO participants VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (p.id, p.first_name, p.last_name, p.birth_date, p.sex, p.city,
         p.enrollment_date, p.review_date, p.window_start),
    )
    cur.executemany(
        "INSERT INTO conditions (participant_id, code, description, onset) VALUES (%s,%s,%s,%s)",
        [(p.id, c.code, c.description, c.onset) for c in p.conditions])
    cur.executemany(
        "INSERT INTO medications (participant_id, code, description, start_date, stop_date, note) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        [(p.id, m.code, m.description, m.start, m.stop, m.note) for m in p.medications])
    cur.executemany(
        "INSERT INTO allergies (participant_id, description, reaction) VALUES (%s,%s,%s)",
        [(p.id, a.description, a.reaction) for a in p.allergies])
    cur.executemany(
        "INSERT INTO encounters VALUES (%s,%s,%s,%s,%s,%s)",
        [(e.id, p.id, e.start, e.encounter_class, e.description, e.reason) for e in p.encounters])
    cur.executemany(
        "INSERT INTO observations (participant_id, obs_date, code, description, value_num, value_text, units) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        [(p.id, o.obs_date, o.code, o.description,
          o.value if isinstance(o.value, float) else None,
          o.value if isinstance(o.value, str) else None, o.units) for o in p.observations])
    cur.executemany(
        "INSERT INTO notes (id, participant_id, note_date, author_role, note_type, text) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        [(n.id, p.id, n.note_date, n.author_role, n.note_type, n.text) for n in p.notes])


def embed_notes(conn: psycopg.Connection, batch_size: int = 64) -> int:
    from fastembed import TextEmbedding  # optional dependency: pip install -e ".[embed]"
    from pgvector.psycopg import register_vector

    register_vector(conn)
    model = TextEmbedding(EMBED_MODEL)
    rows = conn.execute("SELECT id, note_type, text FROM notes ORDER BY id").fetchall()
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        vectors = list(model.embed([f"{kind}: {text}" for _, kind, text in batch]))
        with conn.cursor() as cur:
            cur.executemany("UPDATE notes SET embedding = %s WHERE id = %s",
                            [(v, note_id) for v, (note_id, _, _) in zip(vectors, batch)])
    return len(rows)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cohort-dir", type=Path, default=Path("data/cohort"))
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL", "postgresql://idt:idt@localhost:5432/idt"))
    ap.add_argument("--embed", action="store_true", help="embed notes with a local model for semantic search")
    args = ap.parse_args(argv)

    participants = load_cohort(args.cohort_dir)
    with psycopg.connect(args.database_url) as conn:
        create_schema(conn)
        with conn.cursor() as cur:
            for p in participants:
                insert_participant(cur, p)
        print(f"Loaded {len(participants)} participants, "
              f"{sum(len(p.notes) for p in participants)} notes.")
        if args.embed:
            print(f"Embedded {embed_notes(conn)} notes with {EMBED_MODEL}.")


if __name__ == "__main__":
    main()
