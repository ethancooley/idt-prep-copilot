"""Score a brief against its answer key.

Matching is by evidence, not by wording: a brief catches an answer-key item when one of its items cites
a note that proves it. That makes scoring deterministic, free, and hard to game with vague phrasing.
Care-plan items have no note (the evidence is a missing record), so they match on category plus a
record citation or keyword instead.
"""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from idt_copilot.agent.schema import Brief, BriefItem, Verdict
from idt_copilot.models import AnswerKey, TruthItem

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


@dataclass
class ParticipantScore:
    participant_id: str
    must_surface: int
    caught: int
    high_total: int
    high_caught: int
    missed: list[str]
    distractor_violations: list[str]
    items: int
    extra_items: int
    partially_supported: int
    removed_claims: int
    cost_usd: float
    seconds: float
    llm_calls: int
    caught_by_category: dict[str, list[int]] = field(default_factory=dict)  # category -> [caught, total]
    error: str | None = None

    @property
    def recall(self) -> float:
        return self.caught / self.must_surface if self.must_surface else 1.0


def _care_plan_match(truth: TruthItem, item: BriefItem) -> bool:
    if item.category != "care_plan_due":
        return False
    text = item.statement.lower()
    if truth.id == "flu_vaccine":
        return "record:immunizations" in item.citations or "flu" in text or "influenza" in text
    return True


def _matches(truth: TruthItem, item: BriefItem) -> bool:
    if truth.supporting_note_ids:
        return bool(set(truth.supporting_note_ids) & set(item.citations))
    return _care_plan_match(truth, item)


def _date_phrases(reason: str) -> list[str]:
    """'Fall on Apr 11, 2026 ...' -> ['apr 11', 'april 11', '2026-04-11']."""
    m = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", reason)
    if not m:
        return []
    mon, day, year = m.group(1), int(m.group(2)), m.group(3)
    full = next(x for x in MONTHS if x.startswith(mon))
    month_num = MONTHS.index(full) + 1
    return [f"{mon.lower()} {day}", f"{full.lower()} {day}", f"{year}-{month_num:02d}-{day:02d}"]


def score_brief(brief: Brief, key: AnswerKey) -> ParticipantScore:
    items = brief.items  # removed claims never reach the team, so they cannot count as caught
    caught_ids, used_items = set(), set()
    by_cat: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for truth in key.must_surface:
        by_cat[truth.category][1] += 1
        hits = [i for i, item in enumerate(items) if _matches(truth, item)]
        if hits:
            caught_ids.add(truth.id)
            by_cat[truth.category][0] += 1
            used_items.update(hits)

    violations = []
    for d in key.must_not_surface_as_new:
        phrases = _date_phrases(d.reason)
        for item in items:
            text = item.statement.lower()
            if set(d.note_ids) & set(item.citations) or any(p in text for p in phrases):
                violations.append(f"{d.id}: {item.statement}")

    high = [t for t in key.must_surface if t.severity.value == "high"]
    run = brief.run or {}
    return ParticipantScore(
        participant_id=key.participant_id,
        must_surface=len(key.must_surface),
        caught=len(caught_ids),
        high_total=len(high),
        high_caught=sum(t.id in caught_ids for t in high),
        missed=[f"[{t.severity.value}] {t.summary}" for t in key.must_surface if t.id not in caught_ids],
        distractor_violations=violations,
        items=len(items),
        extra_items=len(items) - len(used_items),
        partially_supported=sum(i.verdict == Verdict.partially_supported for i in items),
        removed_claims=len(brief.removed_claims),
        cost_usd=float(run.get("cost_usd", 0.0)),
        seconds=float(run.get("seconds", 0.0)),
        llm_calls=int(run.get("llm_calls", 0)),
        caught_by_category=dict(by_cat),
    )


def failed_score(key: AnswerKey, error: str) -> ParticipantScore:
    return ParticipantScore(
        participant_id=key.participant_id, must_surface=len(key.must_surface), caught=0,
        high_total=sum(t.severity.value == "high" for t in key.must_surface), high_caught=0,
        missed=[t.summary for t in key.must_surface], distractor_violations=[], items=0, extra_items=0,
        partially_supported=0, removed_claims=0, cost_usd=0.0, seconds=0.0, llm_calls=0, error=error)


def summarize(scores: list[ParticipantScore]) -> dict:
    total = sum(s.must_surface for s in scores)
    high = sum(s.high_total for s in scores)
    items = sum(s.items for s in scores)
    ok = [s for s in scores if not s.error]
    cats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for s in scores:
        for c, (got, n) in s.caught_by_category.items():
            cats[c][0] += got
            cats[c][1] += n
    secs = sorted(s.seconds for s in ok) or [0.0]
    return {
        "participants": len(scores),
        "errors": len(scores) - len(ok),
        "recall": round(sum(s.caught for s in scores) / total, 3) if total else 1.0,
        "high_severity_recall": round(sum(s.high_caught for s in scores) / high, 3) if high else 1.0,
        "perfect_briefs": sum(s.caught == s.must_surface for s in scores),
        "distractor_violations": sum(len(s.distractor_violations) for s in scores),
        "items_per_brief": round(items / len(ok), 1) if ok else 0,
        "extra_item_rate": round(sum(s.extra_items for s in scores) / items, 3) if items else 0.0,
        "partially_supported_items": sum(s.partially_supported for s in scores),
        "removed_claims": sum(s.removed_claims for s in scores),
        "cost_usd_total": round(sum(s.cost_usd for s in scores), 4),
        "cost_usd_per_brief": round(sum(s.cost_usd for s in ok) / len(ok), 4) if ok else 0.0,
        "seconds_median": round(statistics.median(secs), 1),
        "seconds_p90": round(secs[min(len(secs) - 1, int(0.9 * len(secs)))], 1),
        "recall_by_category": {c: {"caught": v[0], "total": v[1], "recall": round(v[0] / v[1], 3)}
                               for c, v in sorted(cats.items())},
    }


def as_dict(score: ParticipantScore) -> dict:
    return {**asdict(score), "recall": round(score.recall, 3)}


def explain(brief: Brief, key: AnswerKey) -> dict:
    """The answer key for one participant, with which brief lines caught each item, for the web app."""
    items = brief.items
    must = []
    for t in key.must_surface:
        hits = [i for i, item in enumerate(items) if _matches(t, item)]
        must.append({"id": t.id, "category": t.category, "severity": t.severity.value, "summary": t.summary,
                     "event_date": t.event_date.isoformat() if t.event_date else None,
                     "note_ids": t.supporting_note_ids, "caught_by": hits})
    old = []
    for d in key.must_not_surface_as_new:
        phrases = _date_phrases(d.reason)
        bad = [i for i, item in enumerate(items)
               if set(d.note_ids) & set(item.citations) or any(p in item.statement.lower() for p in phrases)]
        old.append({"id": d.id, "reason": d.reason, "note_ids": d.note_ids, "reported_by": bad})
    return {"window_start": key.window_start.isoformat(), "review_date": key.review_date.isoformat(),
            "must_surface": must, "old_events": old}
