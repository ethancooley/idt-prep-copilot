"""MCP server exposing read-only chart tools for synthetic PACE participants.

Run it over stdio (how Claude Desktop, Claude Code, and the agent connect):

    python -m idt_copilot.chart.server
"""
from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from idt_copilot.chart.repository import ChartRepository, NotFound

INSTRUCTIONS = """\
Read-only access to SYNTHETIC charts for PACE participants (no real patients).

Each participant has an upcoming interdisciplinary team (IDT) review. The period since their last review
runs from window_start to review_date; tools default to that period when no dates are given.

Every note has an id like "1a2b3c4d-n007". When you report a fact, cite the note id(s) that support it.
If no note or record supports a statement, do not make it. Events dated before window_start are history,
not new changes."""

server = MCPServer(name="idt-chart", title="IDT Prep Copilot chart tools", instructions=INSTRUCTIONS,
                   version="0.2.0")
repo = ChartRepository()


def _call(fn, *args):
    """Turn bad ids and bad dates into clear tool errors the model can recover from."""
    try:
        return fn(*args)
    except (NotFound, ValueError) as e:
        raise ToolError(str(e)) from e


@server.tool()
def list_participants() -> list[dict]:
    """List participants with an upcoming IDT review: id, name, age, review date, window start,
    and how many notes were written since their last review."""
    return _call(repo.list_participants)


@server.tool()
def get_participant_summary(participant_id: str) -> dict:
    """Demographics, active conditions, active medications, allergies, and the review window
    for one participant."""
    return _call(repo.get_participant_summary, participant_id)


@server.tool()
def get_notes(participant_id: str, start_date: str | None = None, end_date: str | None = None,
              author_role: str | None = None, limit: int = 100) -> list[dict]:
    """Interdisciplinary notes in date order. Defaults to the period since the last review.
    Dates are YYYY-MM-DD. author_role filters by discipline (e.g. "nurse", "social worker", "dietitian")."""
    return _call(repo.get_notes, participant_id, start_date, end_date, author_role, limit)


@server.tool()
def get_note(note_id: str) -> dict:
    """Fetch one note by id. Use this to check that a cited note really says what a brief claims."""
    return _call(repo.get_note, note_id)


@server.tool()
def search_notes(participant_id: str, query: str, limit: int = 5, since: str | None = None) -> dict:
    """Search one participant's notes by meaning (e.g. "trouble bathing", "appetite").
    Searches all dates unless `since` (YYYY-MM-DD) is given. Returns mode "semantic" when note
    embeddings are loaded, otherwise "keyword"."""
    return _call(repo.search_notes, participant_id, query, limit, since)


@server.tool()
def get_vitals(participant_id: str, kind: Literal["all", "weight", "blood_pressure"] = "all",
               since: str | None = None) -> dict:
    """Weight and blood pressure readings since the last review (or `since`). Includes the weight
    change in kg, lb, and percent, and a count of readings at or above 140/90."""
    return _call(repo.get_vitals, participant_id, kind, since)


@server.tool()
def get_encounters(participant_id: str, since: str | None = None) -> list[dict]:
    """Encounters such as ED visits and hospital admissions since the last review (or `since`)."""
    return _call(repo.get_encounters, participant_id, since)


@server.tool()
def get_medication_changes(participant_id: str, since: str | None = None) -> dict:
    """Medications started or stopped since the last review (or `since`)."""
    return _call(repo.get_medication_changes, participant_id, since)


@server.tool()
def get_immunizations(participant_id: str) -> dict:
    """Immunizations from the last two years, and whether a flu vaccine is documented this season."""
    return _call(repo.get_immunizations, participant_id)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
