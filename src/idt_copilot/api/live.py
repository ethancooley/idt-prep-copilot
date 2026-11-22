"""Gated live runs: generate a fresh brief on request, protected by an access code and daily caps.

A live run has two halves:

    open_live_run(body, client_id)   checks the access code, the participant and the caps. Returns an
                                     HTTP error, or a LiveRun ticket with the run already logged.
    stream_live_run(ticket)          runs the agent and yields progress events as it works, ending
                                     with {"type": "done", "bundle": ...} or {"type": "error", ...}.

Splitting them means a bad code or a used-up cap still gets a real 401/429 before any streaming
starts. The same code serves the local dev server and the AWS Lambda function. Configuration comes
from the environment:

    IDT_ACCESS_CODE          required; live runs are off when it is not set
    IDT_DAILY_LIVE_LIMIT     runs allowed per day across everyone (default 20)
    IDT_PER_CLIENT_LIMIT     runs allowed per day per visitor (default 3)
    IDT_LIVE_DRAFT_MODEL     optional model overrides for live runs
    IDT_LIVE_VERIFY_MODEL
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from idt_copilot.agent.chart_client import InProcessChartClient
from idt_copilot.agent.graph import AgentConfig, run_agent
from idt_copilot.agent.llm import LLM
from idt_copilot.api import codes, schema
from idt_copilot.chart.repository import ChartRepository, NotFound
from idt_copilot.export.static_bundle import load_answer_key, participant_bundle

@dataclass
class LiveRun:
    run_id: int
    participant_id: str
    participant_name: str
    runs_left_today: int
    repo: ChartRepository
    llm_factory: type | object = LLM
    code: codes.Reserved | None = None  # set when a personal access code started the run


def _error(status: int, message: str) -> tuple[int, dict]:
    return status, {"error": message}


def _client_hash(client_id: str | None) -> str:
    # Store a salted hash, never the visitor's IP address itself.
    salt = os.environ.get("IDT_ACCESS_CODE", "")
    return hashlib.sha256(f"{salt}:{client_id or 'unknown'}".encode()).hexdigest()[:16]


def open_live_run(body: dict, client_id: str | None = None, llm_factory=LLM) -> tuple[int, dict] | LiveRun:
    """Two kinds of code open a live run: the owner code (IDT_ACCESS_CODE, with per-visitor daily caps), and
    personal codes made in the admin console, each with its own run and spending limits. The daily cap
    across everyone applies to both."""
    expected = os.environ.get("IDT_ACCESS_CODE")
    if not expected:
        return _error(503, "Live runs are turned off on this site. Saved briefs are still available.")
    code = str(body.get("access_code", "")).strip()
    owner = hmac.compare_digest(code.encode(), expected.encode())

    repo = ChartRepository(use_embeddings=False)
    conn = repo.conn
    reserved: codes.Reserved | None = None
    if not owner:
        try:
            reserved = codes.reserve_run(conn, code) if code else None
        except codes.CodeRejected as e:
            return _error(e.status, e.message)
        if reserved is None:
            time.sleep(0.5)  # slow down guessing
            return _error(401, "That access code is not valid.")

    def refuse(status: int, message: str) -> tuple[int, dict]:
        if reserved:
            codes.release_run(conn, reserved.code_id)  # the run never started, so it doesn't count
        return _error(status, message)

    participant_id = str(body.get("participant_id", ""))
    try:
        summary = repo.get_participant_summary(participant_id)
    except NotFound:
        return refuse(404, "No participant with that id.")

    daily = int(os.environ.get("IDT_DAILY_LIVE_LIMIT", "20"))
    per_client = int(os.environ.get("IDT_PER_CLIENT_LIMIT", "3"))
    who = _client_hash(client_id)
    schema.ensure_live_runs(conn)
    today = conn.execute("""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE client_hash = %s AND code_id IS NULL) AS mine
        FROM live_runs WHERE created_at >= date_trunc('day', now())""", (who,)).fetchone()
    if today["total"] >= daily:
        return refuse(429, "Today's live runs are used up. Saved briefs are still available; try again tomorrow.")
    if owner and today["mine"] >= per_client:
        return _error(429, f"You have used all {per_client} live runs for today. Saved briefs are still available.")
    run_id = conn.execute(
        "INSERT INTO live_runs (participant_id, client_hash, code_id) VALUES (%s, %s, %s) RETURNING id",
        (participant_id, who, reserved.code_id if reserved else None)).fetchone()["id"]
    if reserved:
        left = min(reserved.runs_left, daily - today["total"] - 1)
    else:
        left = max(0, min(daily - today["total"], per_client - today["mine"]) - 1)
    return LiveRun(run_id, participant_id, f"{summary['first_name']} {summary['last_name']}", max(0, left), repo,
                   llm_factory, reserved)


def stream_live_run(run: LiveRun, heartbeat_seconds: float = 10.0) -> Iterator[dict]:
    """Run the agent in a worker thread and yield its progress events as they happen.

    A heartbeat event goes out whenever the agent is quiet for a while (a long model call), so
    proxies and browsers never see an idle connection."""
    defaults = AgentConfig()
    config = AgentConfig(draft_model=os.environ.get("IDT_LIVE_DRAFT_MODEL", defaults.draft_model),
                         verify_model=os.environ.get("IDT_LIVE_VERIFY_MODEL", defaults.verify_model))
    events: queue.Queue = queue.Queue()
    outcome: dict = {}

    def work() -> None:
        try:
            outcome["llm"] = llm = run.llm_factory()
            outcome["brief"] = asyncio.run(run_agent(run.participant_id, llm, InProcessChartClient(),
                                                     config, emit=events.put))
        except Exception as e:  # reported to the client below
            outcome["error"] = e
        finally:
            events.put(None)

    yield {"type": "start", "participant_id": run.participant_id, "name": run.participant_name,
           "runs_left_today": run.runs_left_today, "code": _code_status(run), "models": {
               "plan": config.plan_model, "gather": config.gather_model,
               "draft": config.draft_model, "verify": config.verify_model}}
    threading.Thread(target=work, daemon=True).start()
    while True:
        try:
            event = events.get(timeout=heartbeat_seconds)
        except queue.Empty:
            yield {"type": "heartbeat"}
            continue
        if event is None:
            break
        yield event

    conn = run.repo.conn
    if "error" in outcome:
        spent = _spent(outcome)  # a failed run still used tokens, so it still counts against the code
        conn.execute("UPDATE live_runs SET status = 'failed', cost_usd = %s WHERE id = %s", (spent, run.run_id))
        if run.code and spent:
            codes.charge(conn, run.code.code_id, spent)
        yield {"type": "error", "message": f"The live run failed: {outcome['error']}"}
        return
    brief = outcome["brief"]
    conn.execute("UPDATE live_runs SET status = 'ok', cost_usd = %s, seconds = %s WHERE id = %s",
                 (brief.run.get("cost_usd"), brief.run.get("seconds"), run.run_id))
    if run.code:
        codes.charge(conn, run.code.code_id, brief.run.get("cost_usd") or 0.0)
        run.code.budget_left = round(run.code.budget_left - (brief.run.get("cost_usd") or 0.0), 4)
    key = load_answer_key(run.participant_id, Path(os.environ.get("IDT_GOLDEN_DIR", "data/golden")))
    bundle = participant_bundle(run.repo, brief, key)
    bundle["live"] = {"runs_left_today": run.runs_left_today, "code": _code_status(run)}
    yield {"type": "done", "bundle": bundle}


def _spent(outcome: dict) -> float:
    llm = outcome.get("llm")
    try:
        return float(llm.usage.as_dict().get("cost_usd", 0.0)) if llm else 0.0
    except Exception:
        return 0.0


def _code_status(run: LiveRun) -> dict | None:
    if not run.code:
        return None
    return {"runs_left": run.code.runs_left, "budget_left": max(0.0, run.code.budget_left)}


def handle_live_run(body: dict, client_id: str | None = None, llm_factory=LLM) -> tuple[int, dict]:
    """Non-streaming version: run to the end and return (status, bundle or error)."""
    opened = open_live_run(body, client_id, llm_factory)
    if isinstance(opened, tuple):
        return opened
    for event in stream_live_run(opened):
        if event["type"] == "done":
            return 200, event["bundle"]
        if event["type"] == "error":
            return 502, {"error": event["message"]}
    return 502, {"error": "The live run ended without a result."}
