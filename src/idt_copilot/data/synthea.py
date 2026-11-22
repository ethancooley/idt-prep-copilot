"""Read Synthea CSV exports into a clean, PACE-relevant base record per participant."""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from idt_copilot.models import Allergy, Condition, Encounter, Medication, Observation

# Synthea also emits social "findings" (employment, education, abuse, criminal record...).
# They are synthetic, but they are not useful for an IDT brief and some are sensitive,
# so we keep clinical disorders plus a short list of clinically relevant findings.
CLINICAL_FINDINGS = {
    "Prediabetes (finding)",
    "Body mass index 30+ - obesity (finding)",
    "Chronic pain (finding)",
    "Chronic low back pain (finding)",
    "Hypertriglyceridemia (finding)",
    "Anemia (disorder)",
}
EXCLUDE_DISORDERS = {"Gingivitis (disorder)", "Gingival disease (disorder)", "Viral sinusitis (disorder)",
                     "Acute viral pharyngitis (disorder)", "Acute bronchitis (disorder)"}

VITAL_CODES = {
    "29463-7": "Body Weight",
    "8480-6": "Systolic Blood Pressure",
    "8462-4": "Diastolic Blood Pressure",
    "8867-4": "Heart rate",
    "4548-4": "Hemoglobin A1c",
    "33914-3": "eGFR",
    "2339-0": "Glucose",
}


@dataclass
class SyntheaPerson:
    id: str
    first_name: str
    last_name: str
    birth_date: date
    sex: str
    city: str
    conditions: list[Condition] = field(default_factory=list)
    medications: list[Medication] = field(default_factory=list)
    allergies: list[Allergy] = field(default_factory=list)
    encounters: list[Encounter] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    immunizations: list[tuple[date, str]] = field(default_factory=list)


def _d(value: str) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def _clean_name(value: str) -> str:
    # Synthea appends digits to names (e.g. "Chong355") so they can never collide with real people.
    return re.sub(r"\d+", "", value).strip()


def _rows(csv_dir: Path, name: str):
    with open(csv_dir / f"{name}.csv", newline="") as f:
        yield from csv.DictReader(f)


def _is_clinical(description: str) -> bool:
    if description in EXCLUDE_DISORDERS:
        return False
    return description.endswith("(disorder)") or description in CLINICAL_FINDINGS


def load_people(csv_dir: Path, history_start: date) -> list[SyntheaPerson]:
    """Load every person, keeping active conditions/meds and records on or after history_start."""
    people: dict[str, SyntheaPerson] = {}
    for r in _rows(csv_dir, "patients"):
        people[r["Id"]] = SyntheaPerson(
            id=r["Id"],
            first_name=_clean_name(r["FIRST"]),
            last_name=_clean_name(r["LAST"]),
            birth_date=_d(r["BIRTHDATE"]),
            sex=r["GENDER"],
            city=r["CITY"],
        )

    seen_conditions: dict[str, set[str]] = defaultdict(set)
    for r in _rows(csv_dir, "conditions"):
        p = people.get(r["PATIENT"])
        if not p or r["STOP"] or not _is_clinical(r["DESCRIPTION"]):
            continue
        if r["DESCRIPTION"] in seen_conditions[p.id]:
            continue
        seen_conditions[p.id].add(r["DESCRIPTION"])
        p.conditions.append(Condition(code=r["CODE"], description=r["DESCRIPTION"], onset=_d(r["START"])))

    seen_meds: dict[str, set[str]] = defaultdict(set)
    for r in _rows(csv_dir, "medications"):
        p = people.get(r["PATIENT"])
        if not p or r["STOP"] or r["DESCRIPTION"] in seen_meds[p.id]:
            continue
        seen_meds[p.id].add(r["DESCRIPTION"])
        p.medications.append(Medication(code=r["CODE"], description=r["DESCRIPTION"], start=_d(r["START"])))

    for r in _rows(csv_dir, "allergies"):
        p = people.get(r["PATIENT"])
        if p and not r["STOP"]:
            p.allergies.append(Allergy(description=r["DESCRIPTION"], reaction=r.get("DESCRIPTION1") or None))

    for r in _rows(csv_dir, "encounters"):
        p = people.get(r["PATIENT"])
        start = _d(r["START"])
        if p and start >= history_start:
            p.encounters.append(Encounter(
                id=r["Id"], start=start, encounter_class=r["ENCOUNTERCLASS"],
                description=r["DESCRIPTION"], reason=r["REASONDESCRIPTION"] or None,
            ))

    for r in _rows(csv_dir, "observations"):
        p = people.get(r["PATIENT"])
        obs_date = _d(r["DATE"])
        if not p or obs_date < history_start or r["CODE"] not in VITAL_CODES:
            continue
        try:
            value: float | str = round(float(r["VALUE"]), 1)
        except ValueError:
            value = r["VALUE"]
        p.observations.append(Observation(
            obs_date=obs_date, code=r["CODE"], description=VITAL_CODES[r["CODE"]],
            value=value, units=r["UNITS"] or None,
        ))

    for r in _rows(csv_dir, "immunizations"):
        p = people.get(r["PATIENT"])
        if p:
            p.immunizations.append((_d(r["DATE"]), r["DESCRIPTION"]))

    for p in people.values():
        p.encounters.sort(key=lambda e: e.start)
        p.observations.sort(key=lambda o: o.obs_date)
    return sorted(people.values(), key=lambda p: p.id)
