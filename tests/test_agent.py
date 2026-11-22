"""Runs the whole LangGraph agent against a scripted stand-in for Claude.

The stand-in follows the same Messages API shapes, so these tests exercise the real graph, the real
MCP tools, and the real database. They check the plumbing and the guardrails, not the model's judgment;
that is what the eval harness in phase 4 is for.
"""
from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace as NS

import psycopg
import pytest

from idt_copilot.agent.chart_client import InProcessChartClient, MCPChartClient
from idt_copilot.agent.graph import AgentConfig, render_markdown, run_agent
from idt_copilot.agent.llm import LLM
from idt_copilot.agent.schema import Verdict
from idt_copilot.chart.repository import ChartRepository

FAKE_ID = "deadbeef-n999"


@pytest.fixture(scope="module")
def participant_id():
    import os
    os.environ["IDT_DISABLE_EMBEDDINGS"] = "1"  # keyword search keeps tests fast and offline
    repo = ChartRepository(use_embeddings=False)
    try:
        pid = repo.list_participants()[0]["id"]
    except psycopg.Error:
        pytest.skip("database not running or not loaded")
    from idt_copilot.chart import server
    server.repo._use_embeddings = False
    return pid


def _response(*blocks, stop="end_turn"):
    return NS(content=list(blocks), stop_reason=stop, usage=NS(input_tokens=1000, output_tokens=200))


def _tool(name, args, i=0):
    return NS(type="tool_use", id=f"toolu_{name}_{i}", name=name, input=args)


class ScriptedClaude:
    """Plays each role in the graph. `stubborn` keeps the bad claim in every draft."""

    def __init__(self, stubborn: bool = False, wrong_participant: bool = False):
        self.stubborn, self.wrong_participant = stubborn, wrong_participant
        self.drafts = 0

    def create(self, **kw):
        choice = (kw.get("tool_choice") or {}).get("name")
        if choice == "submit_plan":
            return _response(_tool("submit_plan", {"checks": ["falls", "weight trend", "medication changes"]}))
        if choice == "submit_brief":
            self.drafts += 1
            evidence = json.loads(kw["messages"][0]["content"].split("Evidence:\n", 1)[1].split("\n\nThe verifier")[0])
            first_note = evidence["notes"][0]["id"]
            items = [{"category": "other", "severity": "medium",
                      "statement": "Something supported by the first note.", "citations": [first_note]},
                     {"category": "vitals", "severity": "low", "statement": "Weight trend reviewed.",
                      "citations": ["record:vitals"]}]
            if self.drafts == 1 or self.stubborn:
                items.append({"category": "fall", "severity": "high", "statement": "Invented fall.",
                              "citations": [FAKE_ID]})
            return _response(_tool("submit_brief", {"headline": "Test headline", "items": items,
                                                    "questions_for_team": ["Anything else?"]}))
        if choice == "submit_verification":
            checked = json.loads(kw["messages"][0]["content"].split("Items to check:\n", 1)[1])
            return _response(_tool("submit_verification", {"results": [
                {"index": c["index"], "verdict": "supported", "reason": "Matches the cited source."}
                for c in checked]}))
        # gather: ask for tools once, then stop
        last = kw["messages"][-1]
        if isinstance(last["content"], list) and last["content"] and last["content"][0].get("type") == "tool_result":
            return _response(NS(type="text", text="Checked notes and search results."))
        pid = "someone-else" if self.wrong_participant else re.search(r"Participant id: (\S+)",
                                                                      kw["messages"][0]["content"]).group(1)
        return _response(_tool("get_notes", {"participant_id": pid}, 1),
                         _tool("search_notes", {"participant_id": pid, "query": "fall"}, 2), stop="tool_use")


def test_bad_citation_triggers_a_second_pass_and_is_dropped(participant_id):
    llm = LLM(ScriptedClaude())
    brief = asyncio.run(run_agent(participant_id, llm, InProcessChartClient(), AgentConfig()))
    assert brief.run["draft_attempts"] == 2
    assert all(FAKE_ID not in i.citations for i in brief.items)
    assert not brief.removed_claims
    assert all(i.verdict == Verdict.supported for i in brief.items)
    assert brief.run["llm_calls"] >= 7 and brief.run["cost_usd"] > 0


def test_claim_that_never_gets_support_is_removed_for_audit(participant_id):
    brief = asyncio.run(run_agent(participant_id, LLM(ScriptedClaude(stubborn=True)), InProcessChartClient()))
    assert [c.statement for c in brief.removed_claims] == ["Invented fall."]
    assert brief.removed_claims[0].verdict == Verdict.unsupported


def test_safety_net_runs_core_tools_and_scopes_to_participant(participant_id):
    brief = asyncio.run(run_agent(participant_id, LLM(ScriptedClaude(wrong_participant=True)),
                                  InProcessChartClient()))
    calls = brief.run["tool_calls"]
    assert all(c["args"]["participant_id"] == participant_id for c in calls)
    assert {"get_vitals", "get_encounters", "get_medication_changes", "get_immunizations"} <= \
           {c["tool"] for c in calls if c["by"] == "safety_net"}
    assert "IDT brief" in render_markdown(brief)


def test_agent_runs_over_real_mcp_stdio(participant_id):
    async def go():
        async with MCPChartClient() as chart:
            return await run_agent(participant_id, LLM(ScriptedClaude()), chart)
    brief = asyncio.run(go())
    assert brief.participant_id == participant_id and brief.items
