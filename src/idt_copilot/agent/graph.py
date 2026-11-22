"""The IDT Prep agent: plan -> gather -> draft -> verify -> (gather again if needed) -> finalize.

    plan      Claude reads the participant summary and lists what to check.
    gather    Claude calls the MCP chart tools; code makes sure the core tools always ran.
    draft     Claude writes a structured brief where every item cites note ids or records.
    verify    Code rejects unknown citations; Claude checks each claim against its cited sources.
              Unsupported claims send the graph back to gather once, with the verifier's feedback.
    finalize  Supported items are kept, partial ones are flagged, unsupported ones are removed
              and listed for audit.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from idt_copilot.agent import prompts
from idt_copilot.agent.chart_client import ChartClient
from idt_copilot.agent.llm import LLM, assistant_blocks, structured
from idt_copilot.agent.schema import (
    BRIEF_TOOL, PLAN_TOOL, RECORD_CITATIONS, VERIFY_TOOL, Brief, BriefItem, Verdict,
)

CORE_TOOLS = ["get_notes", "get_vitals", "get_encounters", "get_medication_changes", "get_immunizations"]
RECORD_SOURCES = {
    "record:vitals": "get_vitals", "record:encounters": "get_encounters",
    "record:medications": "get_medication_changes", "record:immunizations": "get_immunizations",
}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
MAX_TOOL_RESULT_CHARS = 30_000


@dataclass
class AgentConfig:
    plan_model: str = "claude-haiku-5-5"
    gather_model: str = "claude-haiku-5-5"
    draft_model: str = "claude-sonnet-5-5"
    verify_model: str = "claude-sonnet-5-5"
    max_tool_rounds: int = 10
    max_attempts: int = 2  # draft/verify passes before unsupported claims are removed


class AgentState(TypedDict, total=False):
    participant_id: str
    summary: dict
    plan: list[str]
    notes: dict[str, dict]
    records: dict[str, Any]
    tool_calls: list[dict]
    draft: dict
    verification: list[dict]
    feedback: str
    attempts: int
    final: dict


def _absorb(name: str, result: Any, notes: dict, records: dict) -> None:
    """Keep every note the tools returned (for citations) and the latest structured records."""
    if isinstance(result, dict) and "error" in result:
        return
    if name == "get_notes" and isinstance(result, list):
        found = result
    elif name == "search_notes" and isinstance(result, dict):
        found = result.get("results", [])
    elif name == "get_note" and isinstance(result, dict):
        found = [result]
    else:
        found = []
        records[name] = result
    for n in found:
        notes[n["id"]] = {k: n[k] for k in ("id", "note_date", "author_role", "note_type", "text")}


Emit = Callable[[dict], None]


def describe_result(name: str, result: Any) -> str:
    """A one-line, human-readable summary of what a chart tool returned (for the live progress view)."""
    if isinstance(result, dict) and "error" in result:
        return f"error: {result['error']}"
    try:
        if name == "get_notes":
            return f"{len(result)} note{'s' if len(result) != 1 else ''}"
        if name == "search_notes":
            n = len(result.get("results", []))
            return f"{n} matching note{'s' if n != 1 else ''} ({result.get('mode', 'keyword')} search)"
        if name == "get_note":
            return f"{result.get('note_type', 'note')} from {result.get('note_date', '?')}"
        if name == "get_vitals":
            parts = []
            if w := result.get("weight"):
                parts.append(f"{len(w.get('readings', []))} weights")
                if c := w.get("change"):
                    parts.append(f"weight {c['percent']:+.1f}%")
            if bp := result.get("blood_pressure"):
                parts.append(f"{len(bp.get('readings', []))} blood pressures, {bp.get('elevated_count', 0)} high")
            return ", ".join(parts) or "no readings"
        if name == "get_encounters":
            return f"{len(result)} encounter{'s' if len(result) != 1 else ''}"
        if name == "get_medication_changes":
            return f"{len(result.get('started', []))} started, {len(result.get('stopped', []))} stopped"
        if name == "get_immunizations":
            return "flu vaccine this season: " + ("yes" if result.get("flu_vaccine_this_season") else "no")
        if name == "get_participant_summary":
            return (f"age {result.get('age')}, {len(result.get('conditions', []))} conditions, "
                    f"{len(result.get('active_medications', []))} medications")
    except (AttributeError, KeyError, TypeError):
        pass
    return "done"


def build_agent(llm: LLM, chart: ChartClient, config: AgentConfig | None = None, emit: Emit | None = None):
    """`emit` receives a small dict at each step (plan, every tool call, draft, verdicts) so a caller
    can show the agent working. It never changes what the agent does."""
    cfg = config or AgentConfig()
    started = time.perf_counter()

    def send(event: dict) -> None:
        if emit is None:
            return
        try:
            emit({**event, "t": round(time.perf_counter() - started, 1),
                  "cost_usd": llm.usage.as_dict().get("cost_usd", 0)})
        except Exception:  # a broken listener must never break a run
            pass

    async def chart_call(name: str, args: dict, by: str) -> Any:
        shown = {k: v for k, v in args.items() if k != "participant_id"}
        send({"type": "tool_start", "tool": name, "args": shown, "by": by})
        result = await chart.call(name, args)
        send({"type": "tool_end", "tool": name, "args": shown, "by": by,
              "ok": not (isinstance(result, dict) and "error" in result),
              "summary": describe_result(name, result)})
        return result

    async def call_llm(*args, **kwargs):
        return await asyncio.to_thread(llm.call, *args, **kwargs)

    async def call_structured(*args, **kwargs):
        return await asyncio.to_thread(structured, llm, *args, **kwargs)

    async def plan(state: AgentState) -> AgentState:
        pid = state["participant_id"]
        send({"type": "step", "step": "plan", "model": cfg.plan_model})
        summary = await chart_call("get_participant_summary", {"participant_id": pid}, "agent")
        if isinstance(summary, dict) and "error" in summary:
            raise ValueError(summary["error"])
        result = await call_structured("plan", cfg.plan_model, prompts.PLAN,
                                       [{"role": "user", "content": json.dumps(summary)}], PLAN_TOOL, 1500)
        send({"type": "plan", "checks": result["checks"]})
        return {"summary": summary, "plan": result["checks"]}

    async def gather(state: AgentState) -> AgentState:
        pid, summary = state["participant_id"], state["summary"]
        send({"type": "step", "step": "gather", "model": cfg.gather_model,
              "attempt": state.get("attempts", 0) + 1})
        notes, records = dict(state.get("notes", {})), dict(state.get("records", {}))
        calls = list(state.get("tool_calls", []))
        tools = await chart.tools()
        takes_pid = {t["name"] for t in tools if "participant_id" in t["input_schema"].get("properties", {})}
        brief_of_task = (
            f"Participant id: {pid}\nReview period: {summary['window_start']} to {summary['review_date']}\n"
            "Plan:\n" + "\n".join(f"- {c}" for c in state["plan"]))
        if state.get("feedback"):
            brief_of_task += f"\n\nThe verifier flagged problems with the last draft:\n{state['feedback']}\n" \
                             "Look for evidence for these specific claims."
        messages: list[dict] = [{"role": "user", "content": brief_of_task}]
        called: set[str] = {c["tool"] for c in calls}

        for _ in range(cfg.max_tool_rounds):
            resp = await call_llm("gather", cfg.gather_model, prompts.GATHER, messages, max_tokens=1500, tools=tools)
            messages.append({"role": "assistant", "content": assistant_blocks(resp)})
            uses = [b for b in resp.content if b.type == "tool_use"]
            if not uses:
                break
            results = []
            for use in uses:
                args = dict(use.input)
                if use.name in takes_pid:
                    args["participant_id"] = pid  # the agent may only read this participant's chart
                result = await chart_call(use.name, args, "model")
                _absorb(use.name, result, notes, records)
                calls.append({"tool": use.name, "args": args, "by": "model"})
                called.add(use.name)
                results.append({"type": "tool_result", "tool_use_id": use.id,
                                "content": json.dumps(result)[:MAX_TOOL_RESULT_CHARS],
                                "is_error": isinstance(result, dict) and "error" in result})
            messages.append({"role": "user", "content": results})

        # Safety net: the brief must never miss a whole category because the model skipped a tool.
        for name in CORE_TOOLS:
            if name not in called:
                result = await chart_call(name, {"participant_id": pid}, "safety_net")
                _absorb(name, result, notes, records)
                calls.append({"tool": name, "args": {"participant_id": pid}, "by": "safety_net"})
        return {"notes": notes, "records": records, "tool_calls": calls}

    async def draft(state: AgentState) -> AgentState:
        s = state["summary"]
        send({"type": "step", "step": "draft", "model": cfg.draft_model, "notes": len(state["notes"])})
        evidence = {
            "participant": {k: s.get(k) for k in ("id", "first_name", "last_name", "age", "sex", "conditions",
                                                   "active_medications", "allergies")},
            "review_period": {"window_start": s["window_start"], "review_date": s["review_date"]},
            "notes": sorted(state["notes"].values(), key=lambda n: (n["note_date"], n["id"])),
            "records": {cite: state["records"].get(src) for cite, src in RECORD_SOURCES.items()},
        }
        content = "Evidence:\n" + json.dumps(evidence, indent=1)
        if state.get("feedback"):
            content += f"\n\nThe verifier rejected parts of your last draft:\n{state['feedback']}\n" \
                       "Fix or drop those claims."
        draft = await call_structured("draft", cfg.draft_model, prompts.DRAFT,
                                      [{"role": "user", "content": content}], BRIEF_TOOL, 4000)
        send({"type": "draft", "headline": draft.get("headline", ""),
              "items": [{k: i.get(k) for k in ("severity", "category", "statement", "citations")}
                        for i in draft.get("items", [])]})
        return {"draft": draft}

    async def verify(state: AgentState) -> AgentState:
        items = state["draft"].get("items", [])
        send({"type": "step", "step": "verify", "model": cfg.verify_model, "items": len(items)})
        notes, records = state["notes"], state["records"]
        verdicts: dict[int, dict] = {}
        to_check = []
        for i, item in enumerate(items):
            cites = item.get("citations", [])
            known = [c for c in cites if c in notes or (c in RECORD_SOURCES and RECORD_SOURCES[c] in records)]
            unknown = [c for c in cites if c not in known]
            item["citations"] = known
            if not known:
                verdicts[i] = {"index": i, "verdict": Verdict.unsupported.value,
                               "reason": f"No valid citations ({', '.join(unknown) or 'none given'})."}
                continue
            to_check.append({
                "index": i, "statement": item["statement"],
                "cited_notes": [notes[c] for c in known if c in notes],
                "cited_records": {c: records[RECORD_SOURCES[c]] for c in known if c in RECORD_SOURCES},
                **({"note": f"Unknown citations removed: {', '.join(unknown)}"} if unknown else {}),
            })
        if to_check:
            s = state["summary"]
            content = (f"Review period: {s['window_start']} to {s['review_date']}\n\nItems to check:\n"
                       + json.dumps(to_check, indent=1))
            checked = await call_structured("verify", cfg.verify_model, prompts.VERIFY,
                                            [{"role": "user", "content": content}], VERIFY_TOOL, 3000)
            for r in checked["results"]:
                if r["index"] not in verdicts and 0 <= r["index"] < len(items):
                    verdicts[r["index"]] = r
        for i in range(len(items)):  # anything the verifier skipped is not trusted
            verdicts.setdefault(i, {"index": i, "verdict": Verdict.unsupported.value,
                                    "reason": "Verifier returned no verdict."})
        results = [verdicts[i] for i in range(len(items))]
        rejected = [r for r in results if r["verdict"] == Verdict.unsupported.value]
        feedback = "\n".join(f"- \"{items[r['index']]['statement']}\": {r['reason']}" for r in rejected)
        attempts = state.get("attempts", 0) + 1
        send({"type": "verdicts", "attempt": attempts,
              "results": [{"index": r["index"], "verdict": r["verdict"], "reason": r["reason"],
                           "statement": items[r["index"]]["statement"]} for r in results],
              "retry": bool(feedback) and attempts < cfg.max_attempts})
        return {"draft": {**state["draft"], "items": items}, "verification": results,
                "attempts": attempts, "feedback": feedback}

    def after_verify(state: AgentState) -> str:
        if state["feedback"] and state["attempts"] < cfg.max_attempts:
            return "gather"
        return "finalize"

    async def finalize(state: AgentState) -> AgentState:
        s, d = state["summary"], state["draft"]
        kept, removed = [], []
        for item, v in zip(d.get("items", []), state["verification"]):
            bi = BriefItem(**item, verdict=Verdict(v["verdict"]), verifier_note=v["reason"])
            (removed if bi.verdict == Verdict.unsupported else kept).append(bi)
        kept.sort(key=lambda b: SEVERITY_ORDER.get(b.severity, 3))
        brief = Brief(
            participant_id=s["id"], participant_name=f"{s['first_name']} {s['last_name']}",
            review_date=s["review_date"], window_start=s["window_start"], headline=d.get("headline", ""),
            items=kept, questions_for_team=d.get("questions_for_team", []), removed_claims=removed,
            run={"models": {"plan": cfg.plan_model, "gather": cfg.gather_model, "draft": cfg.draft_model,
                            "verify": cfg.verify_model},
                 "draft_attempts": state["attempts"], "tool_calls": state["tool_calls"], **llm.usage.as_dict()},
        )
        send({"type": "step", "step": "finalize", "kept": len(kept), "removed": len(removed)})
        return {"final": brief.model_dump(mode="json")}

    g = StateGraph(AgentState)
    for name, fn in [("plan", plan), ("gather", gather), ("draft", draft), ("verify", verify),
                     ("finalize", finalize)]:
        g.add_node(name, fn)
    g.add_edge(START, "plan")
    g.add_edge("plan", "gather")
    g.add_edge("gather", "draft")
    g.add_edge("draft", "verify")
    g.add_conditional_edges("verify", after_verify, {"gather": "gather", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile()


async def run_agent(participant_id: str, llm: LLM, chart: ChartClient, config: AgentConfig | None = None,
                    emit: Emit | None = None) -> Brief:
    graph = build_agent(llm, chart, config, emit)
    start = time.perf_counter()
    state = await graph.ainvoke({"participant_id": participant_id, "attempts": 0, "notes": {}, "records": {},
                                 "tool_calls": []}, {"recursion_limit": 25})
    brief = Brief.model_validate(state["final"])
    brief.run["seconds"] = round(time.perf_counter() - start, 2)
    return brief


def render_markdown(brief: Brief) -> str:
    lines = [f"# IDT brief: {brief.participant_name}",
             f"Review {brief.review_date} · covers {brief.window_start} onward · synthetic data", "",
             f"**{brief.headline}**", ""]
    for item in brief.items:
        flag = " *(partially supported — check)*" if item.verdict == Verdict.partially_supported else ""
        lines.append(f"- **[{item.severity}] {item.category}** {item.statement}{flag} "
                     f"<sub>{', '.join(item.citations)}</sub>")
    if brief.questions_for_team:
        lines += ["", "## Questions for the team"] + [f"- {q}" for q in brief.questions_for_team]
    if brief.removed_claims:
        lines += ["", "## Removed by the verifier"] + [f"- {c.statement} ({c.verifier_note})"
                                                       for c in brief.removed_claims]
    r = brief.run
    lines += ["", f"<sub>{r.get('llm_calls')} model calls · {len(r.get('tool_calls', []))} tool calls · "
                  f"${r.get('cost_usd')} · {r.get('seconds')}s</sub>"]
    return "\n".join(lines)
