"""HTTP server for live runs. The same server runs locally and on AWS Lambda.

Locally:
    IDT_ACCESS_CODE=letmein python -m idt_copilot.api.server
    # then in web/: VITE_LIVE_API_URL=http://localhost:8787 npm run dev

On Lambda it runs behind the AWS Lambda Web Adapter with response streaming turned on
(deploy/template.yaml), so progress events reach the browser as the agent produces them.

Endpoints:
    GET  /                   health check (the Lambda Web Adapter's readiness check)
    POST /live-run/stream    newline-delimited JSON: one event per line while the agent works
    POST /live-run           plain JSON: waits for the finished brief

Secrets: when IDT_SSM_PREFIX is set (on Lambda), ANTHROPIC_API_KEY, DATABASE_URL and
IDT_ACCESS_CODE are read once at startup from SSM Parameter Store, e.g. /idt-copilot/ANTHROPIC_API_KEY.
They are never written to logs.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from idt_copilot.agent.run import load_dotenv
from idt_copilot.api.live import handle_live_run, open_live_run, stream_live_run

MAX_BODY = 10_000
SECRET_NAMES = ("ANTHROPIC_API_KEY", "DATABASE_URL", "IDT_ACCESS_CODE")


def load_ssm_secrets(prefix: str) -> None:
    import boto3  # included in the Lambda Python runtime; only needed there

    ssm = boto3.client("ssm")
    names = [f"{prefix.rstrip('/')}/{n}" for n in SECRET_NAMES]
    found = ssm.get_parameters(Names=names, WithDecryption=True)
    for param in found["Parameters"]:
        os.environ[param["Name"].rsplit("/", 1)[1]] = param["Value"]
    if found["InvalidParameters"]:
        print(f"Missing SSM parameters: {', '.join(found['InvalidParameters'])}")


def client_ip(headers, fallback: str) -> str:
    forwarded = headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    context = headers.get("x-amzn-request-context")  # added by the Lambda Web Adapter
    if context:
        try:
            return json.loads(context)["http"]["sourceIp"]
        except (ValueError, KeyError, TypeError):
            pass
    return fallback


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # needed for chunked streaming

    def log_message(self, fmt, *args):  # keep request lines, never bodies
        print(f"{self.command} {self.path} {args[1] if len(args) > 1 else ''}")

    def _cors(self) -> None:
        # On Lambda the Function URL adds the CORS headers, so the server must not add them too.
        if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
            return
        origin = os.environ.get("IDT_ALLOWED_ORIGIN", "*")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send(self, status: int, payload: dict | None) -> None:
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict | None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY:
            self._send(413, {"error": "Request too large"})
            return None
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "Request body must be JSON"})
            return None
        if not isinstance(body, dict):
            self._send(400, {"error": "Request body must be a JSON object"})
            return None
        return body

    def do_OPTIONS(self):  # CORS preflight (local development)
        self._send(204, None)

    def do_GET(self):
        if self.path in ("/", "/health"):
            return self._send(200, {"ok": True})
        self._send(404, {"error": "Not found"})

    def do_POST(self):
        if self.path not in ("/live-run", "/live-run/stream"):
            return self._send(404, {"error": "Not found"})
        body = self._body()
        if body is None:
            return
        ip = client_ip(self.headers, self.client_address[0])
        if self.path == "/live-run":
            return self._send(*handle_live_run(body, client_id=ip))

        opened = open_live_run(body, client_id=ip)
        if isinstance(opened, tuple):
            return self._send(*opened)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Transfer-Encoding", "chunked")
        self._cors()
        self.end_headers()
        connected = True
        for event in stream_live_run(opened):
            if not connected:
                continue  # visitor left: let the run finish so it is logged and counted
            line = (json.dumps(event) + "\n").encode()
            try:
                self.wfile.write(f"{len(line):X}\r\n".encode() + line + b"\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                connected = False
        if connected:
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        self.close_connection = True


def main() -> None:
    load_dotenv()
    if os.environ.get("IDT_SSM_PREFIX"):
        load_ssm_secrets(os.environ["IDT_SSM_PREFIX"])
    port = int(os.environ.get("AWS_LWA_PORT") or os.environ.get("PORT") or "8787")
    state = "access code set" if os.environ.get("IDT_ACCESS_CODE") else "IDT_ACCESS_CODE not set: live runs off"
    print(f"Live-run server on http://127.0.0.1:{port} ({state})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
