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
