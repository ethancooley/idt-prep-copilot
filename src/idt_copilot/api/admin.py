"""Admin API for personal access codes. Every request needs the admin password (IDT_ADMIN_TOKEN) as a bearer
token; admin is off entirely when it isn't set.

    GET  /admin/codes                 every code with its usage (never the codes themselves)
    POST /admin/codes                 create one: {label, max_runs, max_cost_usd, expires_in_days}
                                      the response holds the code; it is never shown again
    POST /admin/codes/<id>/revoke     turn a code off
    GET  /admin/runs                  recent live runs, and totals for today
"""
from __future__ import annotations

import hmac
import os
import re
import time

from idt_copilot.api import codes, schema
from idt_copilot.chart.repository import ChartRepository


def _authorized(authorization: str | None) -> tuple[int, dict] | None:
    expected = os.environ.get("IDT_ADMIN_TOKEN")
    if not expected:
        return 503, {"error": "The admin console is turned off on this site."}
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not given or not hmac.compare_digest(given.encode(), expected.encode()):
        time.sleep(0.5)  # slow down guessing
        return 401, {"error": "That admin password is not right."}
    return None


def handle_admin(method: str, path: str, authorization: str | None, body: dict | None = None) -> tuple[int, dict]:
    refused = _authorized(authorization)
    if refused:
        return refused
    conn = ChartRepository(use_embeddings=False).conn
    codes.ensure_schema(conn)
    schema.ensure_live_runs(conn)

    if method == "GET" and path == "/admin/codes":
        return 200, {"codes": codes.list_codes(conn)}

    if method == "POST" and path == "/admin/codes":
        body = body or {}
        try:
            days = body.get("expires_in_days")
            code, record = codes.create_code(conn, str(body.get("label", "")), int(body.get("max_runs", 3)),
                                             float(body.get("max_cost_usd", 5)), int(days) if days else None)
        except (TypeError, ValueError) as e:
            return 400, {"error": str(e) or "Check the values and try again."}
        return 201, {"code": code, "record": record}

    if method == "POST" and (m := re.fullmatch(r"/admin/codes/(\d+)/revoke", path)):
        record = codes.revoke_code(conn, int(m.group(1)))
        return (200, {"record": record}) if record else (404, {"error": "No code with that id."})

    if method == "GET" and path == "/admin/runs":
        rows = conn.execute("""
            SELECT r.created_at, r.status, r.cost_usd, r.seconds, r.participant_id,
                   p.first_name || ' ' || p.last_name AS participant, c.label AS code_label
            FROM live_runs r
            LEFT JOIN participants p ON p.id = r.participant_id
            LEFT JOIN access_codes c ON c.id = r.code_id
            ORDER BY r.created_at DESC LIMIT 50""").fetchall()
        today = conn.execute("""
            SELECT count(*) AS runs, COALESCE(sum(cost_usd), 0) AS cost_usd FROM live_runs
            WHERE created_at >= date_trunc('day', now())""").fetchone()
        return 200, {
            "runs": [{**r, "created_at": r["created_at"].isoformat(), "code_label": r["code_label"] or "Owner code"}
                     for r in rows],
            "today": {"runs": today["runs"], "cost_usd": round(float(today["cost_usd"]), 4),
                      "limit": int(os.environ.get("IDT_DAILY_LIVE_LIMIT", "20"))},
        }

    return 404, {"error": "Not found"}
