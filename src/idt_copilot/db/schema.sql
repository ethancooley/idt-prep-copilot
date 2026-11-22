-- IDT Prep Copilot schema. All data is synthetic.
CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS immunizations, notes, observations, encounters, allergies, medications, conditions, participants CASCADE;

CREATE TABLE participants (
    id              TEXT PRIMARY KEY,
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    birth_date      DATE NOT NULL,
    sex             TEXT NOT NULL,
    city            TEXT NOT NULL,
    enrollment_date DATE NOT NULL,
    review_date     DATE NOT NULL,   -- the upcoming IDT review
    window_start    DATE NOT NULL    -- start of the period since the last review
);

CREATE TABLE conditions (
    id             SERIAL PRIMARY KEY,
    participant_id TEXT NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    code           TEXT NOT NULL,
    description    TEXT NOT NULL,
    onset          DATE NOT NULL
);

CREATE TABLE medications (
    id             SERIAL PRIMARY KEY,
    participant_id TEXT NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    code           TEXT NOT NULL,
    description    TEXT NOT NULL,
    start_date     DATE NOT NULL,
    stop_date      DATE,
    note           TEXT
);

CREATE TABLE allergies (
    id             SERIAL PRIMARY KEY,
    participant_id TEXT NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    description    TEXT NOT NULL,
    reaction       TEXT
);

CREATE TABLE encounters (
    id              TEXT PRIMARY KEY,
    participant_id  TEXT NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    start_date      DATE NOT NULL,
    encounter_class TEXT NOT NULL,
    description     TEXT NOT NULL,
    reason          TEXT
);

CREATE TABLE observations (
    id             SERIAL PRIMARY KEY,
    participant_id TEXT NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    obs_date       DATE NOT NULL,
    code           TEXT NOT NULL,
    description    TEXT NOT NULL,
    value_num      DOUBLE PRECISION,
    value_text     TEXT,
    units          TEXT
);

CREATE TABLE notes (
    id             TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    note_date      DATE NOT NULL,
    author_role    TEXT NOT NULL,
    note_type      TEXT NOT NULL,
    text           TEXT NOT NULL,
    embedding      vector(384)      -- bge-small-en-v1.5; filled by `idt-load-db --embed`
);

CREATE TABLE immunizations (
    id             SERIAL PRIMARY KEY,
    participant_id TEXT NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    imm_date       DATE NOT NULL,
    description    TEXT NOT NULL
);

CREATE INDEX ON conditions (participant_id);
CREATE INDEX ON medications (participant_id);
CREATE INDEX ON encounters (participant_id, start_date);
CREATE INDEX ON observations (participant_id, obs_date);
CREATE INDEX ON notes (participant_id, note_date);
CREATE INDEX ON notes USING hnsw (embedding vector_cosine_ops);
