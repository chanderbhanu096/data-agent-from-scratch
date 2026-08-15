"""The live-demo server. Stdlib only — no Flask, no FastAPI.

    python demo/serve.py            # then open http://localhost:8000

One page, three data sources, one rule: the link is never broken. Pick Cloud and
it runs the real chapter agents against a hosted model; pick Local and it uses
your Ollama; pick Replay (or run out of credits) and it plays back captured real
runs from demo/data/runs.json. When a live mode isn't available, the server falls
back to the recorded run for that question and says so — it never fabricates.

The browser fires one request per column in parallel, so the three columns fill
in as each agent finishes: you watch the answer improve across chapters live.

ponytail: BaseHTTPRequestHandler + JSON. The whole server is routing; all the
real work lives in the chapters this imports.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from demo import spine

INDEX = HERE / "index.html"
# Hosted platforms (Azure App Service, etc.) provide the port via $PORT and need
# a bind on all interfaces; locally this is just localhost:8000.
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Errors that mean "this live mode can't run" rather than "this question broke" —
# for these we fall back to the recorded run instead of showing a red column.
_LIVE_OUTAGE_HINTS = (
    "credential",
    "api key",
    "api_key",
    "quota",
    "insufficient",
    "429",
    "401",
    "403",
    "connection",
    "refused",
    "timeout",
    "OperationNotSupported",
)


def _looks_like_outage(msg: str) -> bool:
    low = msg.lower()
    return any(h.lower() in low for h in _LIVE_OUTAGE_HINTS)


def available_modes() -> dict:
    """Which modes to advertise. A host with no Ollama can hide Local via
    DEMO_DISABLE_LOCAL so the UI never offers a pill that only ever falls back."""
    modes = {m: spine.mode_available(m) for m in ("cloud", "local", "replay")}
    if os.getenv("DEMO_DISABLE_LOCAL"):
        modes["local"] = False
    return modes


def _fallback(question: str, column_id: str, reason: str) -> dict:
    """Serve the captured column for this question, tagged honestly."""
    captured = spine.replay_columns(question) or []
    match = next((c for c in captured if c.get("id") == column_id), None)
    if match is None:
        return {
            "id": column_id,
            "error": f"{reason} — and no captured run exists for this question.",
        }
    return {**match, "fellback": True, "note": f"{reason} — showing a captured real run."}


def resolve_column(question: str, mode: str, column_id: str) -> dict:
    if mode == "replay":
        return _fallback(question, column_id, "Replay mode")

    if not spine.mode_available(mode):
        return _fallback(question, column_id, f"{mode.capitalize()} mode unavailable")

    payload = spine.run_column(column_id, question, mode)
    if payload.get("error") and _looks_like_outage(payload["error"]):
        return _fallback(question, column_id, f"{mode.capitalize()} run failed ({payload['error']})")
    return payload


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the console quiet
        pass

    def _send_json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            body = INDEX.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/config":
            self._send_json(
                {
                    "modes": available_modes(),
                    "questions": spine.demo_questions(),
                    "columns": [
                        {k: c[k] for k in ("id", "chapter", "title", "subtitle")}
                        for c in spine.COLUMNS
                    ],
                }
            )
            return
        self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if self.path != "/api/column":
            self._send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(length) or b"{}")
            question = (req.get("question") or "").strip()
            mode = req.get("mode") or "replay"
            column_id = req.get("column")
            if not question or column_id not in spine.COLUMN_IDS:
                self._send_json({"error": "need a question and a valid column id"}, 400)
                return
            self._send_json(resolve_column(question, mode, column_id))
        except Exception as e:  # noqa: BLE001 — one bad request must not take down the server
            self._send_json({"error": str(e)[:200]}, 500)


def main() -> None:
    modes = available_modes()
    print("Data Agent — live demo")
    print(f"  modes available: {', '.join(m for m, ok in modes.items() if ok) or 'none (capture some runs first)'}")
    print(f"  open http://localhost:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
