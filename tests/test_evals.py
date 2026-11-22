"""Checks the scorer on hand-built briefs and runs the eval pipeline end to end with an oracle model."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from idt_copilot.agent.graph import AgentConfig
from idt_copilot.agent.llm import LLM
from idt_copilot.agent.schema import Brief, BriefItem, Verdict
from idt_copilot.evals.run_evals import generate_briefs, load_keys, main, score_all
from idt_copilot.evals.score import score_brief, summarize
from idt_copilot.models import AnswerKey

GOLDEN = Path(__file__).resolve().parents[1] / "data" / "golden"


def _item_for(truth) -> BriefItem:
    cites = truth.supporting_note_ids or ["record:immunizations"]
    category = truth.category
    return BriefItem(category=category, severity=truth.severity.value, statement=truth.summary,
                     citations=cites, verdict=Verdict.supported)


def _brief(key: AnswerKey, items: list[BriefItem], removed: list[BriefItem] | None = None) -> Brief:
    return Brief(participant_id=key.participant_id, participant_name="Test", review_date=str(key.review_date),
                 window_start=str(key.window_start), headline="", items=items, removed_claims=removed or [],
                 run={"cost_usd": 0.12, "seconds": 30.0, "llm_calls": 7})


@pytest.fixture(scope="module")
def key_with_distractor():
    return next(k for k in load_keys(GOLDEN)
                if k.must_not_surface_as_new and any(t.severity.value == "high" for t in k.must_surface))


def test_perfect_brief_scores_full_marks(key_with_distractor):
    key = key_with_distractor
    s = score_brief(_brief(key, [_item_for(t) for t in key.must_surface]), key)
    assert s.recall == 1.0 and s.high_caught == s.high_total
    assert not s.distractor_violations and s.extra_items == 0


def test_sloppy_brief_is_penalized(key_with_distractor):
    key = key_with_distractor
    high = next(t for t in key.must_surface if t.severity.value == "high")
    items = [_item_for(t) for t in key.must_surface if t is not high]
    old = key.must_not_surface_as_new[0]
    items.append(BriefItem(category="fall", severity="high", statement="Recent fall reported.",
                           citations=old.note_ids))
    s = score_brief(_brief(key, items), key)
    assert s.recall < 1.0 and s.high_caught == s.high_total - 1
    assert len(s.distractor_violations) == 1 and s.extra_items == 1
    assert any(high.summary in m for m in s.missed)


def test_removed_claims_do_not_count_as_caught(key_with_distractor):
    key = key_with_distractor
    removed = [_item_for(t).model_copy(update={"verdict": Verdict.unsupported}) for t in key.must_surface]
    s = score_brief(_brief(key, [], removed), key)
    assert s.caught == 0 and s.removed_claims == len(key.must_surface)


def test_summary_aggregates(key_with_distractor):
    key = key_with_distractor
    perfect = score_brief(_brief(key, [_item_for(t) for t in key.must_surface]), key)
    empty = score_brief(_brief(key, []), key)
    summary = summarize([perfect, empty])
    assert summary["recall"] == 0.5 and summary["perfect_briefs"] == 1
    assert summary["cost_usd_per_brief"] == 0.12


# ------------------------------------------------------------ end to end with an oracle model

class OracleClaude:
    """Drafts the answer key itself, so a correct pipeline must score 100%."""

    def create(self, **kw):
        from test_agent import ScriptedClaude, _response, _tool
        choice = (kw.get("tool_choice") or {}).get("name")
        if choice != "submit_brief":
            return ScriptedClaude().create(**kw)
        evidence = json.loads(kw["messages"][0]["content"].split("Evidence:\n", 1)[1].split("\n\nThe verifier")[0])
        key = AnswerKey.model_validate_json((GOLDEN / f"{evidence['participant']['id']}.json").read_text())
        items = [_item_for(t).model_dump(include={"category", "severity", "statement", "citations"})
                 for t in key.must_surface]
        return _response(_tool("submit_brief", {"headline": "Oracle", "items": items, "questions_for_team": []}))


@pytest.fixture(scope="module")
def db_ready():
    import psycopg

    from idt_copilot.chart.repository import ChartRepository
    os.environ["IDT_DISABLE_EMBEDDINGS"] = "1"
    try:
        ChartRepository(use_embeddings=False).list_participants()
    except psycopg.Error:
        pytest.skip("database not running or not loaded")


def test_pipeline_with_oracle_scores_100_and_rescoring_matches(db_ready, tmp_path):
    keys = load_keys(GOLDEN)[:4]
    briefs = asyncio.run(generate_briefs(keys, tmp_path / "run" / "briefs", AgentConfig(), concurrency=2,
                                         use_mcp=False, make_llm=lambda: LLM(OracleClaude())))
    summary = summarize(score_all(keys, briefs))
    assert summary["errors"] == 0
    assert summary["recall"] == 1.0 and summary["distractor_violations"] == 0

    code = main(["--golden-dir", str(GOLDEN), "--briefs-dir", str(tmp_path / "run" / "briefs"),
                 "--min-recall", "0.99", "--max-distractor-violations", "0"])
    assert code == 0
    saved = json.loads((tmp_path / "run" / "results.json").read_text())
    assert saved["summary"]["recall"] == 1.0 and saved["summary"]["participants"] == 4
    assert "Recall by category" in (tmp_path / "run" / "report.md").read_text()

    assert main(["--golden-dir", str(GOLDEN), "--briefs-dir", str(tmp_path / "run" / "briefs"),
                 "--min-high-recall", "1.01"]) == 1
