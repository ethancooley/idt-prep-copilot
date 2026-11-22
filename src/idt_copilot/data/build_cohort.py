"""Build the synthetic PACE cohort and its evaluation answer keys.

    python -m idt_copilot.data.build_cohort --synthea-dir data/synthea/csv

Writes one participant record per file to data/cohort/ and one answer key per file to data/golden/.
The same seed always produces the same cohort.
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

from idt_copilot.data import scenarios as sc
from idt_copilot.data.synthea import SyntheaPerson, load_people
from idt_copilot.models import AnswerKey, Medication, Observation, Participant


def _routine_vitals(ctx: sc.Context, include_weight: bool, include_bp: bool) -> list[Observation]:
    weights = [o.value for o in ctx.person.observations
               if o.description == "Body Weight" and isinstance(o.value, float)]
    base_w = weights[-1] if weights else round(ctx.rng.uniform(55, 85), 1)
    obs = []
    for offset in (8, 38, 68):
        d = ctx.window_start + timedelta(days=offset + ctx.rng.randint(0, 6))
        if include_weight:
            obs.append(Observation(obs_date=d, code="29463-7", description="Body Weight",
                                   value=round(base_w + ctx.rng.uniform(-0.6, 0.6), 1), units="kg"))
        if include_bp:
            obs += [
                Observation(obs_date=d, code="8480-6", description="Systolic Blood Pressure",
                            value=float(ctx.rng.randint(118, 138)), units="mm[Hg]"),
                Observation(obs_date=d, code="8462-4", description="Diastolic Blood Pressure",
                            value=float(ctx.rng.randint(70, 84)), units="mm[Hg]"),
            ]
    return obs


def build_participant(person: SyntheaPerson, review_date: date, window_days: int, seed: int
                      ) -> tuple[Participant, AnswerKey]:
    rng = random.Random(f"{seed}-{person.id}")
    window_start = review_date - timedelta(days=window_days)
    ctx = sc.Context(
        person=person, window_start=window_start, review_date=review_date,
        caregiver=rng.choice(sc.CAREGIVER_NAMES), caregiver_relation=rng.choice(sc.CAREGIVER_RELATIONS), rng=rng,
    )

    eligible = [name for name, (_, ok) in sc.EVENTS.items() if ok(ctx)]
    picks = rng.sample(eligible, rng.randint(2, 4))
    outcomes = [sc.EVENTS[name][0](ctx) for name in picks]
    outcomes.append(sc.flu_vaccine_due(ctx))
    if rng.random() < 0.5:
        outcomes.append(sc.old_event_distractor(ctx))

    notes = sc.routine_notes(ctx, rng.randint(6, 10))
    observations = _routine_vitals(ctx, include_weight="weight_loss" not in picks,
                                   include_bp="bp_uncontrolled" not in picks)
    encounters, new_meds, stopped, truth, distractors = [], [], {}, [], []
    for o in outcomes:
        notes += o.notes
        observations += o.observations
        encounters += o.encounters
        new_meds += o.new_meds
        stopped.update(o.stopped_meds)
        truth += o.truth
        distractors += o.distractors

    # Keep Synthea history from BEFORE the window only. Everything inside the window comes from the
    # scenarios above, so the answer key is complete: the chart holds no unplanned "new" events.
    history_start = window_start - timedelta(days=365)
    medications = [
        Medication(**{**m.model_dump(), "stop": stopped.get(m.description)})
        for m in person.medications if m.start < window_start
    ] + new_meds

    participant = Participant(
        id=person.id,
        first_name=person.first_name,
        last_name=person.last_name,
        birth_date=person.birth_date,
        sex=person.sex,
        city=person.city,
        enrollment_date=window_start - timedelta(days=rng.randint(200, 900)),
        review_date=review_date,
        window_start=window_start,
        conditions=[c for c in person.conditions if c.onset < window_start],
        medications=medications,
        allergies=person.allergies,
        encounters=sorted([e for e in person.encounters if history_start <= e.start < window_start] + encounters,
                          key=lambda e: e.start),
        observations=sorted([o for o in person.observations if history_start <= o.obs_date < window_start]
                            + observations, key=lambda o: o.obs_date),
        notes=sorted(notes, key=lambda n: (n.note_date, n.id)),
    )
    key = AnswerKey(participant_id=person.id, review_date=review_date, window_start=window_start,
                    must_surface=truth, must_not_surface_as_new=distractors)
    return participant, key


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--synthea-dir", type=Path, default=Path("data/synthea/csv"))
    ap.add_argument("--out-dir", type=Path, default=Path("data"))
    ap.add_argument("--review-date", type=date.fromisoformat, default=date(2026, 11, 30))
    ap.add_argument("--window-days", type=int, default=90)
    ap.add_argument("--seed", type=int, default=20261121)
    args = ap.parse_args(argv)

    window_start = args.review_date - timedelta(days=args.window_days)
    people = load_people(args.synthea_dir, history_start=window_start - timedelta(days=365))
    cohort_dir, golden_dir = args.out_dir / "cohort", args.out_dir / "golden"
    for d in (cohort_dir, golden_dir):
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.json"):
            old.unlink()

    index = []
    for person in people:
        participant, key = build_participant(person, args.review_date, args.window_days, args.seed)
        (cohort_dir / f"{participant.id}.json").write_text(participant.model_dump_json(indent=2))
        (golden_dir / f"{participant.id}.json").write_text(key.model_dump_json(indent=2))
        index.append({"id": participant.id, "name": f"{participant.first_name} {participant.last_name}",
                      "age": participant.age, "notes": len(participant.notes),
                      "must_surface": [t.category for t in key.must_surface]})
    (cohort_dir / "index.json").write_text(json.dumps(index, indent=2))
    print(f"Wrote {len(index)} synthetic participants to {cohort_dir} and answer keys to {golden_dir}")


if __name__ == "__main__":
    main()
