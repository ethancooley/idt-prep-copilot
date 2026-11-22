"""Data models for synthetic PACE participants and their evaluation answer keys.

Every record in this project is synthetic. Nothing here describes a real person.
"""
from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class Condition(BaseModel):
    code: str
    description: str
    onset: date


class Medication(BaseModel):
    code: str
    description: str
    start: date
    stop: date | None = None
    note: str | None = None  # e.g. "started after ED visit", "dose increased"

    @property
    def active(self) -> bool:
        return self.stop is None


class Allergy(BaseModel):
    description: str
    reaction: str | None = None


class Immunization(BaseModel):
    imm_date: date
    description: str


class Encounter(BaseModel):
    id: str
    start: date
    encounter_class: str
    description: str
    reason: str | None = None


class Observation(BaseModel):
    obs_date: date
    code: str
    description: str
    value: float | str
    units: str | None = None


class Note(BaseModel):
    id: str
    note_date: date
    author_role: str
    note_type: str
    text: str


class Participant(BaseModel):
    id: str
    first_name: str
    last_name: str
    birth_date: date
    sex: str
    city: str
    enrollment_date: date
    review_date: date
    window_start: date = Field(description="Start of the period since the last IDT review")
    conditions: list[Condition]
    medications: list[Medication]
    allergies: list[Allergy]
    encounters: list[Encounter]
    observations: list[Observation]
    notes: list[Note]
    immunizations: list[Immunization] = Field(default_factory=list)

    @property
    def age(self) -> int:
        r, b = self.review_date, self.birth_date
        return r.year - b.year - ((r.month, r.day) < (b.month, b.day))


class Severity(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class TruthItem(BaseModel):
    """One thing a good IDT brief must surface, with the records that prove it."""

    id: str
    category: str
    severity: Severity
    summary: str
    event_date: date | None = None
    supporting_note_ids: list[str] = Field(default_factory=list)


class Distractor(BaseModel):
    """Something in the chart a brief should NOT report as new (e.g. it happened before the window)."""

    id: str
    reason: str
    note_ids: list[str]


class AnswerKey(BaseModel):
    participant_id: str
    review_date: date
    window_start: date
    must_surface: list[TruthItem]
    must_not_surface_as_new: list[Distractor] = Field(default_factory=list)
    reviewed_by_human: bool = False
