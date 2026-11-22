# IDT Prep Copilot

> **All data in this project is synthetic.** No real patients, no PHI.

An agentic AI copilot for PACE care teams. Before each interdisciplinary team (IDT) meeting, it reads a
participant's chart, drafts a one-page brief of what changed and what the team should discuss, links every
line to the note it came from, and leaves the final call to a clinician.

## Status

| Phase | What | Status |
| --- | --- | --- |
| 1 | Synthetic data foundation: cohort, answer keys, Postgres + pgvector | Done |
| 2 | MCP server with chart tools | Done |
| 3 | LangGraph agent on Claude: plan, gather, draft, verify citations | Done |
| 4 | Eval harness against the answer keys | Done |
| 5 | React app: brief with clickable citations, approve/edit/reject, audit log | Next |
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

## Chart tools (MCP server)

`src/idt_copilot/chart/server.py` exposes read-only tools over the
[Model Context Protocol](https://modelcontextprotocol.io). The agent gets chart facts only through these tools,
and every note comes back with an id the brief must cite.

| Tool | Returns |
| --- | --- |
| `list_participants` | Who is up for IDT review, with note counts since the last review |
| `get_participant_summary` | Demographics, conditions, active medications, allergies, review window |
| `get_notes` | Interdisciplinary notes, defaulting to the period since the last review; filter by date or discipline |
| `get_note` | One note by id, used to verify citations |
| `search_notes` | Semantic search over a participant's notes (keyword fallback if embeddings are not loaded) |
| `get_vitals` | Weight and blood pressure trends, with weight change in kg, lb, and percent |
| `get_encounters` | ED visits and hospital admissions |
| `get_medication_changes` | Medications started or stopped |

**Try it in Claude Code** (from the repo, with the database running):

```bash
claude mcp add idt-chart -e DATABASE_URL=postgresql://idt:idt@localhost:5432/idt \
  -- "$PWD/.venv/bin/python" -m idt_copilot.chart.server
```

**Or in Claude Desktop**, add this to `claude_desktop_config.json` (use your own absolute path):

```json
{
  "mcpServers": {
    "idt-chart": {
      "command": "/absolute/path/to/idt-prep-copilot/.venv/bin/python",
      "args": ["-m", "idt_copilot.chart.server"],
      "env": { "DATABASE_URL": "postgresql://idt:idt@localhost:5432/idt" }
    }
  }
}
```

Then ask: *"Using the idt-chart tools, what changed for Mariana Arriaga since her last IDT review? Cite note ids."*

## The agent

`src/idt_copilot/agent/graph.py` is a [LangGraph](https://langchain-ai.github.io/langgraph/) state machine:

| Step | Model | What happens |
| --- | --- | --- |
| Plan | Claude Haiku | Reads the participant summary and lists what to check |
| Gather | Claude Haiku | Calls the MCP chart tools; code guarantees the core tools always run and every call is scoped to this participant |
| Draft | Claude Sonnet | Writes a structured brief; every item must cite note ids or records |
| Verify | Code + Claude Sonnet | Code rejects citations that do not exist; Claude checks each claim against its cited sources |
| Retry | | Unsupported claims send the graph back to Gather once, with the verifier's reasons |
| Finalize | | Keeps supported items, flags partial ones, and lists removed claims for audit |

Each run records model calls, tokens, cost, latency, and every tool call.

```bash
cp .env.example .env      # add your ANTHROPIC_API_KEY
python -m idt_copilot.agent.run --participant "Mariana Arriaga"
```

The brief prints as Markdown and is saved to `briefs/` as JSON and Markdown. By default the agent reaches the
chart through the MCP server over stdio, just like Claude Desktop; `--in-process` skips the subprocess.

The tests run the full graph against a scripted stand-in for Claude, so they need no API key.

## Evaluation

`src/idt_copilot/evals/` runs the agent across all 40 answer keys and scores every brief. Matching is by
evidence, not wording: a brief catches an answer-key item only when one of its items cites a note that proves
it, so scoring is deterministic and costs nothing.

| Metric | What it measures |
| --- | --- |
| Recall | Share of answer-key items the brief caught |
| High-severity recall | The same, for falls, ED visits, new confusion, weight loss, and other high-severity items |
| Old events reported as new | Items about events from before the review period (target: 0) |
| Items not tied to an answer-key item | A precision signal: extra items the team did not need |
| Claims removed by the verifier | Draft claims that failed citation checks and never reached the team |
| Cost and time per brief | From the run log of every brief |

```bash
python -m idt_copilot.evals.run_evals --limit 5          # quick live run against Claude
python -m idt_copilot.evals.run_evals                    # all 40 participants
python -m idt_copilot.evals.run_evals --briefs-dir evals/runs/<run>/briefs --min-recall 0.9 \
    --max-distractor-violations 0                        # re-score saved briefs for free; exits 1 below the bar
```

Each run writes `evals/runs/<timestamp>/` with the briefs, `results.json`, and a Markdown `report.md`.

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
  chart/repository.py  Read-only chart queries used by the tools
  chart/server.py      MCP server exposing the chart tools
  agent/graph.py       LangGraph agent: plan, gather, draft, verify, finalize
  agent/chart_client.py  Reaches the chart over MCP (stdio) or in process
  agent/llm.py         Anthropic client wrapper with token and cost tracking
  agent/run.py         CLI: generate a brief for one participant
  evals/score.py       Scores a brief against its answer key
  evals/run_evals.py   Runs the agent across the cohort, writes results and a report
tests/                 Cohort, chart tool, agent, and eval checks
```
