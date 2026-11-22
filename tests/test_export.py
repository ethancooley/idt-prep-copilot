"""Checks the static bundle the public site serves."""
from __future__ import annotations

import json

import psycopg
import pytest

from idt_copilot.export.static_bundle import main


@pytest.fixture(scope="module")
def bundle_dir(tmp_path_factory):
    from idt_copilot.chart.repository import ChartRepository
    try:
        ChartRepository(use_embeddings=False).list_participants()
    except psycopg.Error:
        pytest.skip("database not running or not loaded")
    out = tmp_path_factory.mktemp("data")
    main(["--sample", "--out-dir", str(out)])
    return out


def test_index_lists_every_participant_most_urgent_first(bundle_dir):
    index = json.loads((bundle_dir / "index.json").read_text())
    assert index["source"] == "sample" and len(index["participants"]) == 40
    highs = [p["counts"]["high"] for p in index["participants"]]
    assert highs == sorted(highs, reverse=True)


def test_every_citation_resolves_inside_its_bundle(bundle_dir):
    for path in (bundle_dir / "p").glob("*.json"):
        b = json.loads(path.read_text())
        notes = {n["id"] for n in b["notes"]}
        for item in b["brief"]["items"]:
            for cite in item["citations"]:
                assert cite in notes or cite in b["records"], (path.name, cite)


def test_bundles_carry_the_answer_key_and_older_notes(bundle_dir):
    for path in (bundle_dir / "p").glob("*.json"):
        b = json.loads(path.read_text())
        key = b["answer_key"]
        notes = {n["id"] for n in b["notes"]}
        older = {n["id"] for n in b["older_notes"]}
        # sample briefs are built from the key, so every planted event is caught by some line
        assert key["must_surface"] and all(t["caught_by"] for t in key["must_surface"])
        for t in key["must_surface"]:
            assert all(n in notes for n in t["note_ids"])
        for d in key["old_events"]:
            assert all(n in older or n in notes for n in d["note_ids"])
            assert all(n["note_date"] < key["window_start"] for n in b["older_notes"])


def test_agent_runs_record_a_replayable_trace():
    import asyncio
    import os

    from test_agent import ScriptedClaude

    from idt_copilot.agent.chart_client import InProcessChartClient
    from idt_copilot.agent.graph import run_agent
    from idt_copilot.agent.llm import LLM
    from idt_copilot.chart.repository import ChartRepository
    os.environ["IDT_DISABLE_EMBEDDINGS"] = "1"
    try:
        pid = ChartRepository(use_embeddings=False).list_participants()[0]["id"]
    except psycopg.Error:
        pytest.skip("database not running or not loaded")
    brief = asyncio.run(run_agent(pid, LLM(ScriptedClaude()), InProcessChartClient()))
    trace = brief.run["trace"]
    kinds = {e["type"] for e in trace}
    assert {"step", "plan", "tool_start", "tool_end", "draft", "verdicts"} <= kinds
    assert json.loads(json.dumps(trace)) == trace  # saved with the brief as plain JSON
