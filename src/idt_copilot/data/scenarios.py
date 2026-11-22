"""PACE-specific clinical events layered on top of a Synthea base record.

Synthea gives realistic conditions, medications, encounters and vitals, but its notes are thin
templates. A PACE care team works from interdisciplinary notes: nursing, therapy, social work,
dietary, day center and home care. This module writes those notes for a review window and,
because it knows exactly which events it planted, it also writes the answer key used for evals.

Everything generated here is fictional.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from idt_copilot.data.synthea import SyntheaPerson
from idt_copilot.models import (
    Distractor, Encounter, Medication, Note, Observation, Severity, TruthItem,
)

CAREGIVER_NAMES = ["Maria", "Linda", "James", "Denise", "Robert", "Angela", "Marcus", "Teresa", "Kevin", "Rosa"]
CAREGIVER_RELATIONS = ["daughter", "son", "spouse", "niece", "grandson"]


@dataclass
class Context:
    person: SyntheaPerson
    window_start: date
    review_date: date
    caregiver: str
    caregiver_relation: str
    rng: random.Random
    _note_counter: int = 0

    @property
    def first(self) -> str:
        return self.person.first_name

    @property
    def she(self) -> str:
        return "she" if self.person.sex == "F" else "he"

    @property
    def her(self) -> str:
        """Possessive pronoun (her/his)."""
        return "her" if self.person.sex == "F" else "his"

    @property
    def them(self) -> str:
        """Object pronoun (her/him)."""
        return "her" if self.person.sex == "F" else "him"

    @property
    def window_days(self) -> int:
        return (self.review_date - self.window_start).days

    def day(self, lo: int, hi: int) -> date:
        """A date lo..hi days into the review window."""
        return self.window_start + timedelta(days=self.rng.randint(lo, min(hi, self.window_days - 1)))

    def has(self, *keywords: str) -> bool:
        text = " ".join(c.description.lower() for c in self.person.conditions)
        return any(k in text for k in keywords)

    def has_med(self, keyword: str) -> str | None:
        for m in self.person.medications:
            if keyword.lower() in m.description.lower():
                return m.description
        return None

    def note(self, note_date: date, role: str, note_type: str, text: str) -> Note:
        self._note_counter += 1
        return Note(
            id=f"{self.person.id[:8]}-n{self._note_counter:03d}",
            note_date=note_date, author_role=role, note_type=note_type, text=" ".join(text.split()),
        )


@dataclass
class Outcome:
    notes: list[Note] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    encounters: list[Encounter] = field(default_factory=list)
    new_meds: list[Medication] = field(default_factory=list)
    stopped_meds: dict[str, date] = field(default_factory=dict)
    truth: list[TruthItem] = field(default_factory=list)
    distractors: list[Distractor] = field(default_factory=list)


def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


# ---------------------------------------------------------------- events

def fall(ctx: Context) -> Outcome:
    d = ctx.day(5, 70)
    place = ctx.rng.choice(["bathroom at night", "kitchen while reaching for a cabinet", "bedroom getting out of bed"])
    injury, injury_short = ctx.rng.choice([
        ("No injury noted on assessment.", "no injury"),
        ("Small skin tear to left forearm, cleaned and dressed.", "a skin tear to the left forearm"),
        ("Bruising to right hip; able to bear weight, no deformity.", "right hip bruising"),
    ])
    rn = ctx.note(d, "Registered nurse", "Nursing note", f"""
        {ctx.first} reported a fall at home on {_fmt(d)} in the {place}. {ctx.her.capitalize()} {ctx.caregiver_relation}
        {ctx.caregiver} found {ctx.them} on the floor. Denies head strike or loss of consciousness. {injury}
        Vitals stable. Fall risk reassessed as high. PT referral placed for gait evaluation.""")
    pt_day = min(d + timedelta(days=ctx.rng.randint(3, 8)), ctx.review_date - timedelta(days=1))
    pt = ctx.note(pt_day, "Physical therapist", "Therapy evaluation", f"""
        PT evaluation following fall on {_fmt(d)}. Gait slow and unsteady with intermittent cane use;
        Timed Up and Go 19 seconds. Recommend front-wheeled walker, home safety evaluation, and grab bars in
        the bathroom. Will see twice weekly for strength and balance.""")
    return Outcome(notes=[rn, pt], truth=[TruthItem(
        id="fall", category="fall", severity=Severity.high, event_date=d,
        summary=f"Fall at home on {_fmt(d)} with {injury_short}; PT recommends a walker and home safety evaluation.",
        supporting_note_ids=[rn.id, pt.id],
    )])


def ed_visit(ctx: Context) -> Outcome:
    d = ctx.day(10, 70)
    options = [
        ("urinary tract infection with acute confusion", "nitrofurantoin 100 MG Oral Capsule", 5),
        ("dehydration and dizziness", None, 0),
        ("chest pain; cardiac workup negative", None, 0),
    ]
    if ctx.has("pulmonary", "emphysema", "bronchitis", "asthma"):
        options.append(("COPD exacerbation", "predniSONE 40 MG Oral Tablet", 5))
    reason, med, days = ctx.rng.choice(options)
    admitted = ctx.rng.random() < 0.4
    los = ctx.rng.randint(2, 4) if admitted else 0
    stay = f"admitted for {los} days" if admitted else "treated and released the same day"
    discharge_day = d + timedelta(days=los)
    out = Outcome()
    out.encounters.append(Encounter(
        id=f"{ctx.person.id[:8]}-ed1", start=d, encounter_class="inpatient" if admitted else "emergency",
        description="Hospital admission" if admitted else "Emergency department visit", reason=reason,
    ))
    med_line = f"Discharged on {med.split(' Oral')[0]} for {days} days." if med else "No new medications at discharge."
    dc = ctx.note(discharge_day, "Hospital physician", "ED/hospital discharge summary", f"""
        Seen at partner hospital emergency department on {_fmt(d)} for {reason}; {stay}. {med_line}
        Follow up with PACE primary care within 7 days.""")
    fu_day = min(discharge_day + timedelta(days=ctx.rng.randint(2, 6)), ctx.review_date - timedelta(days=1))
    pcp = ctx.note(fu_day, "Primary care physician", "Post-acute follow-up", f"""
        Post-hospital follow-up for {reason}. {ctx.first} is back to baseline per {ctx.her} {ctx.caregiver_relation}.
        Reviewed discharge medications. Will monitor closely over the next two weeks.""")
    out.notes += [dc, pcp]
    if med:
        out.new_meds.append(Medication(code="ed-rx", description=med, start=discharge_day,
                                       stop=discharge_day + timedelta(days=days), note="short course after ED visit"))
    label = "Hospital admission" if admitted else "ED visit"
    out.truth.append(TruthItem(
        id="acute_visit", category="hospital_or_ed", severity=Severity.high, event_date=d,
        summary=f"{label} on {_fmt(d)} for {reason}" + (f" ({los} days)" if admitted else "") + ".",
        supporting_note_ids=[dc.id, pcp.id],
    ))
    return out


def med_change(ctx: Context) -> Outcome:
    d = ctx.day(5, 75)
    out = Outcome()
    stoppable = ctx.has_med("naproxen") or ctx.has_med("diphenhydramine")
    if stoppable and ctx.rng.random() < 0.5:
        why = ("given declining kidney function and fall risk" if "aproxen" in stoppable
               else "as it is on the Beers list and increases confusion and fall risk in older adults")
        pcp = ctx.note(d, "Primary care physician", "Progress note", f"""
            Medication review. Discontinued {stoppable} {why}. Discussed alternatives with {ctx.first};
            acetaminophen as needed for pain.""")
        ph = ctx.note(d + timedelta(days=1), "Pharmacist", "Medication reconciliation", f"""
            Reconciled list after PCP visit. {stoppable} removed from active medications; pharmacy notified.""")
        out.notes += [pcp, ph]
        out.stopped_meds[stoppable] = d
        out.truth.append(TruthItem(
            id="med_change", category="medication_change", severity=Severity.medium, event_date=d,
            summary=f"Stopped {stoppable.split(' Oral')[0]} on {_fmt(d)} {why}.",
            supporting_note_ids=[pcp.id, ph.id]))
        return out
    new, reason, severity = ctx.rng.choice([
        ("apixaban 5 MG Oral Tablet", "new atrial fibrillation found on ECG", Severity.high),
        ("sertraline 25 MG Oral Tablet", "depressive symptoms (PHQ-9 of 14)", Severity.medium),
        ("furosemide 20 MG Oral Tablet", "lower-extremity edema and weight gain", Severity.medium),
    ])
    pcp = ctx.note(d, "Primary care physician", "Progress note", f"""
        Started {new} for {reason}. Discussed risks and benefits with {ctx.first} and {ctx.her}
        {ctx.caregiver_relation}. Recheck in 4 weeks.""")
    ph = ctx.note(d + timedelta(days=2), "Pharmacist", "Medication reconciliation", f"""
        Added {new} to the active list. Checked interactions; counseled on side effects.
        Blister pack updated.""")
    out.notes += [pcp, ph]
    out.new_meds.append(Medication(code="new-rx", description=new, start=d, note=f"started for {reason}"))
    out.truth.append(TruthItem(
        id="med_change", category="medication_change", severity=severity, event_date=d,
        summary=f"Started {new.split(' Oral')[0]} on {_fmt(d)} for {reason}.",
        supporting_note_ids=[pcp.id, ph.id]))
    return out


def weight_loss(ctx: Context) -> Outcome:
    weights = [o.value for o in ctx.person.observations
               if o.description == "Body Weight" and isinstance(o.value, float)]
    base = weights[-1] if weights else round(ctx.rng.uniform(55, 85), 1)
    pct = ctx.rng.uniform(0.06, 0.09)
    out = Outcome()
    for i, frac in enumerate([0.0, 0.35, 0.7, 1.0]):
        out.observations.append(Observation(
            obs_date=ctx.window_start + timedelta(days=4 + i * (ctx.window_days - 10) // 3),
            code="29463-7", description="Body Weight", value=round(base * (1 - pct * frac), 1), units="kg"))
    first, last = out.observations[0], out.observations[-1]
    lost_lb = round((first.value - last.value) * 2.2046)
    d = last.obs_date
    dn = ctx.note(d, "Dietitian", "Nutrition assessment", f"""
        Weight {last.value} kg, down from {first.value} kg on {_fmt(first.obs_date)} ({pct:.0%}).
        {ctx.first} reports poor appetite and skipping breakfast. Eating about 50% of day center lunches.
        Plan: oral nutrition supplement twice daily, weekly weights, and dental check for chewing problems.""")
    out.notes.append(dn)
    out.truth.append(TruthItem(
        id="weight_loss", category="weight_loss", severity=Severity.high, event_date=d,
        summary=f"Weight down about {lost_lb} lb ({pct:.0%}) since {_fmt(first.obs_date)} with poor appetite; supplement started.",
        supporting_note_ids=[dn.id]))
    return out


def functional_decline(ctx: Context) -> Outcome:
    d = ctx.day(20, 80)
    aide_day = d - timedelta(days=ctx.rng.randint(4, 10))
    aide = ctx.note(aide_day, "Home care aide", "Home care visit", f"""
        {ctx.first} needed hands-on help getting out of the tub today and said {ctx.she} has been
        skipping showers because {ctx.she} is afraid of slipping.""")
    ot = ctx.note(d, "Occupational therapist", "Therapy evaluation", f"""
        ADL reassessment. {ctx.first} now needs moderate assistance with bathing and lower-body dressing;
        independent at last review. Recommend tub transfer bench, handheld shower, and increasing
        home care hours for bathing support.""")
    return Outcome(notes=[aide, ot], truth=[TruthItem(
        id="functional_decline", category="functional_status", severity=Severity.medium, event_date=d,
        summary="Now needs moderate help with bathing and lower-body dressing (independent at last review); OT recommends more home care hours.",
        supporting_note_ids=[aide.id, ot.id])])


def missed_attendance(ctx: Context) -> Outcome:
    d = ctx.day(40, 85)
    missed = ctx.rng.randint(4, 6)
    dc = ctx.note(d, "Day center coordinator", "Attendance note", f"""
        {ctx.first} has missed {missed} of the last 8 scheduled day center days. When present, {ctx.she}
        stays quiet and leaves activities early.""")
    sw = ctx.note(d + timedelta(days=2), "Social worker", "Social work note", f"""
        Called {ctx.first} about missed day center days. Reports feeling "down" and not wanting to leave the
        house since a close friend died last month. Will screen for depression and offer grief support.""")
    return Outcome(notes=[dc, sw], truth=[TruthItem(
        id="missed_attendance", category="psychosocial", severity=Severity.medium, event_date=d,
        summary=f"Missed {missed} of last 8 day center days; low mood after a friend's death. Depression screen planned.",
        supporting_note_ids=[dc.id, sw.id])])


def caregiver_strain(ctx: Context) -> Outcome:
    d = ctx.day(15, 85)
    sw = ctx.note(d, "Social worker", "Social work note", f"""
        Met with {ctx.caregiver}, {ctx.first}'s {ctx.caregiver_relation} and primary caregiver. {ctx.caregiver}
        reports exhaustion and poor sleep, and is worried about managing evenings alone. Requests respite.
        Discussed respite options and caregiver support group.""")
    return Outcome(notes=[sw], truth=[TruthItem(
        id="caregiver_strain", category="caregiver", severity=Severity.medium, event_date=d,
        summary=f"Primary caregiver ({ctx.caregiver_relation}) reports burnout and is requesting respite.",
        supporting_note_ids=[sw.id])])


def new_confusion(ctx: Context) -> Outcome:
    d = ctx.day(30, 85)
    rn = ctx.note(d, "Registered nurse", "Nursing note", f"""
        {ctx.caregiver} reports {ctx.first} has been more confused in the evenings for about two weeks,
        once leaving the stove on. Oriented to person and place today but not date. No fever. Plan: urinalysis,
        medication review, and PCP visit this week.""")
    return Outcome(notes=[rn], truth=[TruthItem(
        id="new_confusion", category="cognition", severity=Severity.high, event_date=d,
        summary="New evening confusion for about two weeks, including leaving the stove on; workup ordered.",
        supporting_note_ids=[rn.id])])


def bp_uncontrolled(ctx: Context) -> Outcome:
    out = Outcome()
    readings = []
    for lo, hi in [(25, 35), (45, 55), (65, 75)]:
        d = ctx.day(lo, hi)
        s, di = ctx.rng.randint(158, 176), ctx.rng.randint(88, 98)
        readings.append((d, s, di))
        out.observations += [
            Observation(obs_date=d, code="8480-6", description="Systolic Blood Pressure", value=float(s), units="mm[Hg]"),
            Observation(obs_date=d, code="8462-4", description="Diastolic Blood Pressure", value=float(di), units="mm[Hg]"),
        ]
    last_d, s, di = readings[-1]
    rn = ctx.note(last_d, "Registered nurse", "Nursing note", f"""
        Blood pressure {s}/{di} today, third elevated reading this month. {ctx.first} admits to missing
        evening doses some days. Reinforced adherence; flagged for PCP review of antihypertensive regimen.""")
    out.notes.append(rn)
    out.truth.append(TruthItem(
        id="bp_uncontrolled", category="vitals", severity=Severity.medium, event_date=last_d,
        summary=f"Blood pressure elevated on three readings (latest {s}/{di}) with missed evening doses.",
        supporting_note_ids=[rn.id]))
    return out


EVENTS = {
    "fall": (fall, lambda c: True),
    "ed_visit": (ed_visit, lambda c: True),
    "med_change": (med_change, lambda c: True),
    "weight_loss": (weight_loss, lambda c: True),
    "functional_decline": (functional_decline, lambda c: True),
    "missed_attendance": (missed_attendance, lambda c: True),
    "caregiver_strain": (caregiver_strain, lambda c: True),
    "new_confusion": (new_confusion, lambda c: True),
    "bp_uncontrolled": (bp_uncontrolled, lambda c: c.has("hypertension")),
}


# ---------------------------------------------------------------- background and distractors

def routine_notes(ctx: Context, count: int) -> list[Note]:
    templates = [
        ("Day center coordinator", "Attendance note",
         "{first} attended day center, joined chair exercise and music group, and ate most of lunch."),
        ("Registered nurse", "Nursing note",
         "Routine check. Vitals within {her} usual range. Medications taken as directed. No new concerns."),
        ("Home care aide", "Home care visit",
         "Assisted with light housekeeping and meal prep. {first} in good spirits."),
        ("Primary care physician", "Progress note",
         "Chronic conditions reviewed and stable. Continue current plan."),
        ("Recreation therapist", "Activity note",
         "{first} enjoyed the gardening group and talked about growing tomatoes as a child."),
        ("Driver", "Transportation note", "Picked up for day center on time; no issues during transport."),
    ]
    notes = []
    for _ in range(count):
        role, kind, text = ctx.rng.choice(templates)
        notes.append(ctx.note(ctx.day(1, ctx.window_days - 2), role, kind,
                              text.format(first=ctx.first, her=ctx.her)))
    return notes


def old_event_distractor(ctx: Context) -> Outcome:
    """A real event from BEFORE the window, so the brief should not report it as new."""
    d = ctx.window_start - timedelta(days=ctx.rng.randint(45, 150))
    rn = ctx.note(d, "Registered nurse", "Nursing note", f"""
        {ctx.first} slipped on the porch step on {_fmt(d)}. No injury. Handrail installed the following week.""")
    return Outcome(notes=[rn], distractors=[Distractor(
        id="old_fall", reason=f"Fall on {_fmt(d)} happened before this review period and was resolved.",
        note_ids=[rn.id])])


def flu_vaccine_due(ctx: Context) -> Outcome:
    season_start = date(ctx.review_date.year if ctx.review_date.month >= 8 else ctx.review_date.year - 1, 8, 1)
    if any(d >= season_start and "influenza" in desc.lower() for d, desc in ctx.person.immunizations):
        return Outcome()
    return Outcome(truth=[TruthItem(
        id="flu_vaccine", category="care_plan_due", severity=Severity.low,
        summary="No seasonal flu vaccine documented this season.", supporting_note_ids=[])])
