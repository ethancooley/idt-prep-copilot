"""Personal access codes: limits, revoking, expiry, and the admin API that manages them."""
from __future__ import annotations

import psycopg
import pytest

from idt_copilot.api import codes, schema
from idt_copilot.api.admin import handle_admin
from idt_copilot.api.live import handle_live_run
from idt_copilot.chart.repository import ChartRepository
from test_live import _scripted

ADMIN = "Bearer admin-secret"


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("IDT_DISABLE_EMBEDDINGS", "1")
    repo = ChartRepository(use_embeddings=False)
    try:
        pid = repo.list_participants()[0]["id"]
        repo.conn.execute("DROP TABLE IF EXISTS live_runs; DROP TABLE IF EXISTS access_codes")
        schema.forget()
    except psycopg.Error:
        pytest.skip("database not running or not loaded")
    monkeypatch.setenv("IDT_ACCESS_CODE", "owner-code")
    monkeypatch.setenv("IDT_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("IDT_DAILY_LIVE_LIMIT", "20")
    monkeypatch.setenv("IDT_PER_CLIENT_LIMIT", "1")
    yield pid, repo.conn
    repo.conn.execute("DROP TABLE IF EXISTS live_runs; DROP TABLE IF EXISTS access_codes")
    schema.forget()


def make(label="Emily", runs=3, cost=5.0, days=30):
    status, body = handle_admin("POST", "/admin/codes", ADMIN,
                                {"label": label, "max_runs": runs, "max_cost_usd": cost, "expires_in_days": days})
    assert status == 201
    return body["code"], body["record"]


def run(pid, code, ip="1.1.1.1"):
    return handle_live_run({"participant_id": pid, "access_code": code}, ip, llm_factory=_scripted)


def test_codes_look_right_and_are_never_stored(env):
    _, conn = env
    code, record = make()
    assert code.startswith("IDT-") and len(code) == 13 and not set(code[4:].replace("-", "")) & set("01ILO")
    stored = conn.execute("SELECT * FROM access_codes").fetchone()
    assert stored["code_hash"] == codes.fingerprint(code) and code not in str(stored)
    listed = handle_admin("GET", "/admin/codes", ADMIN)[1]["codes"]
    assert listed[0]["label"] == "Emily" and listed[0]["state"] == "active"
    assert "code_hash" not in listed[0] and code not in str(listed)


def test_a_code_stops_after_its_run_limit_and_ignores_the_per_visitor_cap(env):
    pid, _ = env
    code, _ = make(runs=3)
    statuses = [run(pid, code, ip="same-visitor")[0] for _ in range(3)]
    assert statuses == [200, 200, 200]           # per-visitor cap of 1 applies to the owner code only
    status, body = run(pid, code)
    assert status == 429 and "used all of its live runs" in body["error"]
    record = handle_admin("GET", "/admin/codes", ADMIN)[1]["codes"][0]
    assert record["runs_used"] == 3 and record["cost_used_usd"] > 0 and record["state"] == "used_up"


def test_the_spending_limit_stops_a_code(env):
    pid, conn = env
    code, record = make(runs=10, cost=0.5)
    conn.execute("UPDATE access_codes SET cost_used_usd = 0.45 WHERE id = %s", (record["id"],))
    assert run(pid, code)[0] == 429              # less than $0.10 left, so no new run starts


def test_revoked_and_expired_codes_are_refused(env):
    pid, conn = env
    code, record = make()
    assert handle_admin("POST", f"/admin/codes/{record['id']}/revoke", ADMIN)[0] == 200
    status, body = run(pid, code)
    assert status == 403 and "turned off" in body["error"]

    code2, record2 = make(label="Old")
    conn.execute("UPDATE access_codes SET expires_at = now() - interval '1 day' WHERE id = %s", (record2["id"],))
    status, body = run(pid, code2)
    assert status == 403 and "expired" in body["error"]


def test_codes_are_forgiving_about_case_and_dashes(env):
    pid, _ = env
    code, _ = make()
    assert run(pid, code.lower().replace("-", " "))[0] == 200


def test_a_refused_run_gives_its_reservation_back(env):
    pid, _ = env
    code, _ = make(runs=1)
    assert handle_live_run({"participant_id": "missing", "access_code": code})[0] == 404
    assert run(pid, code)[0] == 200              # the 404 didn't use up the only run


def test_unknown_codes_and_the_owner_code(env):
    pid, _ = env
    assert run(pid, "IDT-AAAA-BBBB")[0] == 401
    assert run(pid, "owner-code", ip="me")[0] == 200
    assert run(pid, "owner-code", ip="me")[0] == 429   # owner code keeps its per-visitor cap


def test_admin_needs_the_password(env, monkeypatch):
    assert handle_admin("GET", "/admin/codes", None)[0] == 401
    assert handle_admin("GET", "/admin/codes", "Bearer wrong")[0] == 401
    assert handle_admin("POST", "/admin/codes", "Bearer wrong", {"label": "x"})[0] == 401
    monkeypatch.delenv("IDT_ADMIN_TOKEN")
    assert handle_admin("GET", "/admin/codes", ADMIN)[0] == 503


def test_admin_validates_new_codes_and_lists_runs(env):
    pid, _ = env
    assert handle_admin("POST", "/admin/codes", ADMIN, {"label": "", "max_runs": 3})[0] == 400
    assert handle_admin("POST", "/admin/codes", ADMIN, {"label": "x", "max_runs": 0})[0] == 400
    assert handle_admin("POST", "/admin/codes", ADMIN, {"label": "x", "max_cost_usd": 500})[0] == 400
    code, _ = make(label="Recruiter")
    run(pid, code)
    body = handle_admin("GET", "/admin/runs", ADMIN)[1]
    assert body["runs"][0]["code_label"] == "Recruiter" and body["runs"][0]["participant"]
    assert body["today"]["runs"] == 1 and body["today"]["limit"] == 20


def test_parallel_first_requests_set_up_tables_once(env):
    """The admin page loads codes and runs at the same moment; both must succeed on a fresh database."""
    import threading
    _, conn = env
    conn.execute("DROP TABLE IF EXISTS live_runs; DROP TABLE IF EXISTS access_codes")
    schema.forget()
    results = []
    threads = [threading.Thread(target=lambda p=p: results.append(handle_admin("GET", p, ADMIN)[0]))
               for p in ("/admin/codes", "/admin/runs") * 3]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results == [200] * 6


def test_more_runs_bring_a_used_up_code_back(env):
    pid, _ = env
    code, record = make(runs=1)
    assert run(pid, code)[0] == 200
    assert run(pid, code)[0] == 429
    status, body = handle_admin("POST", f"/admin/codes/{record['id']}/update", ADMIN,
                                {"max_runs": 3, "max_cost_usd": 5, "expires": "keep"})
    assert status == 200 and body["record"]["state"] == "active" and body["record"]["max_runs"] == 3
    assert body["record"]["expires_at"] == record["expires_at"]   # "keep" leaves the expiry alone
    assert run(pid, code)[0] == 200


def test_an_expired_code_can_be_extended_but_a_turned_off_one_cannot(env):
    pid, conn = env
    code, record = make()
    conn.execute("UPDATE access_codes SET expires_at = now() - interval '1 day' WHERE id = %s", (record["id"],))
    status, body = handle_admin("POST", f"/admin/codes/{record['id']}/update", ADMIN,
                                {"max_runs": 3, "max_cost_usd": 5, "expires": "30"})
    assert status == 200 and body["record"]["state"] == "active"
    assert run(pid, code)[0] == 200

    handle_admin("POST", f"/admin/codes/{record['id']}/revoke", ADMIN)
    status, body = handle_admin("POST", f"/admin/codes/{record['id']}/update", ADMIN,
                                {"max_runs": 9, "max_cost_usd": 5, "expires": "keep"})
    assert status == 409 and "stay off" in body["error"]
    assert handle_admin("POST", "/admin/codes/99999/update", ADMIN, {"max_runs": 3, "max_cost_usd": 5})[0] == 404
