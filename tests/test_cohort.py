"""Checks that the synthetic cohort and its answer keys are internally consistent."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from idt_copilot.data.build_cohort import build_participant
from idt_copilot.data.synthea import load_people
from idt_copilot.db.load import load_cohort
from idt_copilot.models import AnswerKey

ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "data" / "cohort"
GOLDEN = ROOT / "data" / "golden"
SYNTHEA = ROOT / "data" / "synthea" / "csv"


@pytest.fixture(scope="module")
def cohort():
    participants = load_cohort(COHORT)
    keys = {p.id: AnswerKey.model_validate_json((GOLDEN / f"{p.id}.json").read_text()) for p in participants}
    return participants, keys


def test_cohort_has_participants(cohort):
    participants, _ = cohort
    assert len(participants) >= 30
    assert all(p.age >= 55 for p in participants)


def test_names_are_cleaned(cohort):
    participants, _ = cohort
    for p in participants:
        assert not re.search(r"\d", p.first_name + p.last_name)


def test_every_truth_item_is_supported_by_notes_in_the_window(cohort):
    participants, keys = cohort
    for p in participants:
        notes = {n.id: n for n in p.notes}
        for item in keys[p.id].must_surface:
            if item.category == "care_plan_due":
                continue  # absence of a record is the evidence
            assert item.supporting_note_ids, item
            for note_id in item.supporting_note_ids:
                assert note_id in notes, (p.id, note_id)
                assert p.window_start <= notes[note_id].note_date < p.review_date


def test_distractors_sit_before_the_window(cohort):
    participants, keys = cohort
    for p in participants:
        notes = {n.id: n for n in p.notes}
        for d in keys[p.id].must_not_surface_as_new:
            assert all(notes[i].note_date < p.window_start for i in d.note_ids)


def test_no_unplanned_events_inside_the_window(cohort):
    """In-window encounters, meds and conditions must all come from planted scenarios,
    otherwise the answer key would be incomplete."""
    participants, keys = cohort
    for p in participants:
        categories = {t.category for t in keys[p.id].must_surface}
        for e in p.encounters:
            if e.start >= p.window_start:
                assert "hospital_or_ed" in categories
        for m in p.medications:
            if m.start >= p.window_start or (m.stop and m.stop >= p.window_start and m.code not in ("ed-rx",)):
                assert categories & {"medication_change", "hospital_or_ed"}, (p.id, m.description)
        assert all(c.onset < p.window_start for c in p.conditions)


@pytest.mark.skipif(not SYNTHEA.exists(), reason="raw Synthea CSVs not present")
def test_generation_is_deterministic():
    review = date(2026, 11, 30)
    person = load_people(SYNTHEA, history_start=date(2025, 9, 1))[0]
    a = build_participant(person, review, 90, seed=7)
    b = build_participant(person, review, 90, seed=7)
    assert a[0].model_dump_json() == b[0].model_dump_json()
    assert a[1].model_dump_json() == b[1].model_dump_json()
