"""Checks that the chart tools surface the evidence each answer key depends on.

Needs the database from `docker compose up -d` and `python -m idt_copilot.db.load`; skipped otherwise.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import psycopg
import pytest

from idt_copilot.chart.repository import ChartRepository, NotFound
from idt_copilot.models import AnswerKey

GOLDEN = Path(__file__).resolve().parents[1] / "data" / "golden"


@pytest.fixture(scope="module")
def repo():
    r = ChartRepository(use_embeddings=False)
    try:
        r.conn.execute("SELECT 1 FROM participants LIMIT 1")
    except psycopg.Error:
        pytest.skip("database not running or not loaded")
    yield r
    r.close()


@pytest.fixture(scope="module")
def keys():
    return [AnswerKey.model_validate_json(p.read_text()) for p in sorted(GOLDEN.glob("*.json"))]


def test_list_participants(repo):
    people = repo.list_participants()
    assert len(people) == 40
    assert all(p["notes_since_last_review"] > 0 for p in people)


def test_default_notes_hold_every_supporting_note(repo, keys):
    for key in keys:
        ids = {n["id"] for n in repo.get_notes(key.participant_id)}
        for item in key.must_surface:
            assert set(item.supporting_note_ids) <= ids, (key.participant_id, item.id)


def test_default_notes_exclude_history(repo, keys):
    for key in keys:
        ids = {n["id"] for n in repo.get_notes(key.participant_id)}
        for d in key.must_not_surface_as_new:
            assert not set(d.note_ids) & ids


def test_structured_tools_match_answer_keys(repo, keys):
    for key in keys:
        pid, cats = key.participant_id, {t.category for t in key.must_surface}
        if "hospital_or_ed" in cats:
            assert repo.get_encounters(pid)
        else:
            assert not repo.get_encounters(pid)
        if "medication_change" in cats:
            changes = repo.get_medication_changes(pid)
            assert changes["started"] or changes["stopped"]
        vitals = repo.get_vitals(pid)
        if "weight_loss" in cats:
            assert vitals["weight"]["change"]["percent"] <= -5
        else:
            assert abs(vitals["weight"]["change"]["percent"]) < 3
        assert (vitals["blood_pressure"]["elevated_count"] >= 3) == ("vitals" in cats)


def test_immunizations_match_flu_answer_key(repo, keys):
    for key in keys:
        due = any(t.id == "flu_vaccine" for t in key.must_surface)
        assert repo.get_immunizations(key.participant_id)["flu_vaccine_this_season"] is (not due)


def test_search_finds_the_dietitian_note(repo, keys):
    key = next(k for k in keys if any(t.category == "weight_loss" for t in k.must_surface))
    item = next(t for t in key.must_surface if t.category == "weight_loss")
    hits = repo.search_notes(key.participant_id, "appetite weight")["results"]
    assert item.supporting_note_ids[0] in {h["id"] for h in hits}


def test_summary_and_note_lookup(repo, keys):
    key = keys[0]
    summary = repo.get_participant_summary(key.participant_id)
    assert summary["window_start"] == key.window_start.isoformat()
    note_id = repo.get_notes(key.participant_id)[0]["id"]
    assert repo.get_note(note_id)["participant_id"] == key.participant_id


def test_bad_inputs_raise_clear_errors(repo, keys):
    with pytest.raises(NotFound):
        repo.get_notes("not-a-real-id")
    with pytest.raises(ValueError):
        repo.get_notes(keys[0].participant_id, start_date="11/01/2026")


def test_mcp_server_exposes_tools(repo):
    from idt_copilot.chart import server

    server.repo._use_embeddings = False
    names = {t.name for t in asyncio.run(server.server.list_tools())}
    assert names == {"list_participants", "get_participant_summary", "get_notes", "get_note",
                     "search_notes", "get_vitals", "get_encounters", "get_medication_changes",
                     "get_immunizations"}
