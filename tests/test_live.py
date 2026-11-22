"""Checks the gate in front of live runs: access code, daily caps, and the shape of the response."""
from __future__ import annotations

import psycopg
import pytest

from idt_copilot.agent.llm import LLM
from idt_copilot.api import schema
from idt_copilot.api.live import handle_live_run
from idt_copilot.chart.repository import ChartRepository


@pytest.fixture()
def live_env(monkeypatch):
    monkeypatch.setenv("IDT_DISABLE_EMBEDDINGS", "1")
    repo = ChartRepository(use_embeddings=False)
    try:
        pid = repo.list_participants()[0]["id"]
        repo.conn.execute("DROP TABLE IF EXISTS live_runs")
        schema.forget()
        schema.forget()
    except psycopg.Error:
        pytest.skip("database not running or not loaded")
    monkeypatch.setenv("IDT_ACCESS_CODE", "correct-code")
    monkeypatch.setenv("IDT_DAILY_LIVE_LIMIT", "3")
    monkeypatch.setenv("IDT_PER_CLIENT_LIMIT", "2")
    yield pid
    repo.conn.execute("DROP TABLE IF EXISTS live_runs")
    schema.forget()


def _scripted():
    from test_agent import ScriptedClaude
    return LLM(ScriptedClaude())


def test_live_runs_off_without_access_code(monkeypatch):
    monkeypatch.delenv("IDT_ACCESS_CODE", raising=False)
    status, body = handle_live_run({"participant_id": "x", "access_code": "y"})
    assert status == 503 and "turned off" in body["error"]


def test_wrong_code_and_unknown_participant(live_env):
    assert handle_live_run({"participant_id": live_env, "access_code": "nope"})[0] == 401
    assert handle_live_run({"participant_id": "missing", "access_code": "correct-code"})[0] == 404


def test_successful_run_returns_bundle_and_counts_down(live_env):
    status, body = handle_live_run({"participant_id": live_env, "access_code": "correct-code"}, "1.2.3.4",
                                   llm_factory=_scripted)
    assert status == 200
    assert body["brief"]["participant_id"] == live_env
    assert {"participant", "notes", "records"} <= set(body)
    assert body["live"]["runs_left_today"] == 1


def test_per_client_and_daily_caps(live_env):
    call = lambda ip: handle_live_run({"participant_id": live_env, "access_code": "correct-code"}, ip,
                                      llm_factory=_scripted)[0]
    assert call("a") == 200 and call("a") == 200
    assert call("a") == 429          # per-visitor cap of 2
    assert call("b") == 200          # third run overall
    assert call("c") == 429          # daily cap of 3


def test_stream_shows_each_step_in_order(live_env):
    from idt_copilot.api.live import open_live_run, stream_live_run
    opened = open_live_run({"participant_id": live_env, "access_code": "correct-code"}, "s", llm_factory=_scripted)
    events = list(stream_live_run(opened))
    kinds = [e["type"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done"
    steps = [e["step"] for e in events if e["type"] == "step"]
    # the scripted model invents a fall on the first draft, so the graph goes back to gather once
    assert steps == ["plan", "gather", "draft", "verify", "gather", "draft", "verify", "finalize"]
    assert events[kinds.index("plan")]["checks"]
    tool_ends = [e for e in events if e["type"] == "tool_end"]
    assert {"get_participant_summary", "get_notes", "get_vitals"} <= {e["tool"] for e in tool_ends}
    assert all("participant_id" not in e["args"] and e["summary"] for e in tool_ends)
    first_verdicts = next(e for e in events if e["type"] == "verdicts")
    assert first_verdicts["retry"] and any(r["verdict"] == "unsupported" for r in first_verdicts["results"])
    assert [e["t"] for e in events if "t" in e] == sorted(e["t"] for e in events if "t" in e)
    assert events[-1]["bundle"]["brief"]["participant_id"] == live_env


def test_stream_reports_a_failed_run(live_env):
    from idt_copilot.api.live import open_live_run, stream_live_run

    class Broken:
        def create(self, **kw):
            raise RuntimeError("model unavailable")

    opened = open_live_run({"participant_id": live_env, "access_code": "correct-code"}, "f",
                           llm_factory=lambda: LLM(Broken()))
    events = list(stream_live_run(opened))
    assert events[-1]["type"] == "error" and "model unavailable" in events[-1]["message"]
    status = opened.repo.conn.execute("SELECT status FROM live_runs WHERE id = %s", (opened.run_id,)).fetchone()
    assert status["status"] == "failed"


def test_streaming_endpoint_over_http(live_env, monkeypatch):
    """Runs the real HTTP server and reads the chunked stream line by line, the way the browser does."""
    import json
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from idt_copilot.api import live, server

    monkeypatch.setattr(live, "LLM", lambda: _scripted())
    monkeypatch.setattr(live.open_live_run, "__defaults__", (None, lambda: _scripted()))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        def post(body):
            req = urllib.request.Request(f"{url}/live-run/stream", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            return urllib.request.urlopen(req, timeout=30)

        with pytest.raises(urllib.error.HTTPError) as bad:
            post({"participant_id": live_env, "access_code": "nope"})
        assert bad.value.code == 401

        with post({"participant_id": live_env, "access_code": "correct-code"}) as r:
            assert r.headers["Content-Type"] == "application/x-ndjson"
            events = [json.loads(line) for line in r if line.strip()]
        assert events[0]["type"] == "start" and events[-1]["type"] == "done"
        assert urllib.request.urlopen(f"{url}/", timeout=5).status == 200
    finally:
        httpd.shutdown()


def test_client_ip_prefers_forwarded_headers():
    from idt_copilot.api.server import client_ip
    assert client_ip({"X-Forwarded-For": "9.9.9.9, 10.0.0.1"}, "127.0.0.1") == "9.9.9.9"
    ctx = '{"http": {"sourceIp": "8.8.4.4"}}'
    assert client_ip({"x-amzn-request-context": ctx}, "127.0.0.1") == "8.8.4.4"
    assert client_ip({}, "127.0.0.1") == "127.0.0.1"
