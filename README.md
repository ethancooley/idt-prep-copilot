# IDT Prep Copilot

> **All data in this project is synthetic.** No real patients, no PHI.

An agentic AI copilot for PACE care teams. Before each interdisciplinary team (IDT) meeting, it reads a
participant's chart, drafts a one-page brief of what changed and what the team should discuss, links every
line to the note it came from, and leaves the final call to a clinician.

## Status

| Phase | What | Status |
| --- | --- | --- |
| 1 | Synthetic data foundation: cohort, answer keys, Postgres + pgvector | Done |
| 2 | MCP server with chart tools | Next |
| 3 | LangGraph agent on Claude: plan, gather, draft, verify citations | |
| 4 | Eval harness against the answer keys, run in CI | |
| 5 | React app: brief with clickable citations, approve/edit/reject, audit log | |
| 6 | Docker, GitHub Actions, AWS deployment, tracing | |

## The data

The cohort is built in two layers:

1. **[Synthea](https://github.com/synthetichealth/synthea)** generates 40 fictional Californians aged 68 to 92
   with realistic conditions, medications, allergies, encounters, and vitals.
2. **PACE scenarios** (`src/idt_copilot/data/scenarios.py`) add a 90-day review window of interdisciplinary
   notes from nurses, therapists, social workers, dietitians, the day center, home care aides, and pharmacists.
   Each participant gets 2 to 4 planted events, such as a fall, an ED visit, a medication change, weight loss,
   functional decline, new confusion, missed day-center days, caregiver strain, or uncontrolled blood pressure,
   plus routine notes and, for about half, an older event from *before* the window.

Because the generator knows exactly which events it planted, it also writes an **answer key** for each
participant (`data/golden/`): what a good brief must surface, which notes prove it, and which older events it
must not report as new. Synthea records from inside the window are dropped so the chart holds no unplanned
changes and the answer key stays complete. These keys drive the evaluations in phase 4.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,embed]"

# Optional: regenerate the base population (needs Java 17+). The built cohort is already in data/cohort.
./scripts/generate_synthea.sh
python -m idt_copilot.data.build_cohort

# Load into Postgres with pgvector
docker compose up -d
python -m idt_copilot.db.load --embed

pytest
```

## Layout

```
src/idt_copilot/
  models.py            Participant, Note, AnswerKey, ...
  data/synthea.py      Reads Synthea CSVs, keeps clinically relevant records
  data/scenarios.py    PACE events, interdisciplinary notes, and answer keys
  data/build_cohort.py Builds data/cohort and data/golden
  db/schema.sql        Postgres + pgvector schema
  db/load.py           Loads the cohort; --embed adds note embeddings (local model, no API cost)
tests/                 Cohort consistency checks
```
