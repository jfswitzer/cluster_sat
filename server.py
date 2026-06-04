from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from cluster_sat_runtime import BenchmarkRunner, preview_csv


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
RUNS = {}
RUNS_LOCK = threading.Lock()


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8") or "{}")


def _serve_file(handler: BaseHTTPRequestHandler, path: Path) -> None:
    if not path.exists() or not path.is_file():
        handler.send_error(404, "File not found")
        return

    data = path.read_bytes()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class AppHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.path == "/api/health":
            return _json_response(self, 200, {"ok": True})

        if parsed.path == "/api/runs":
            with RUNS_LOCK:
                runs = {run_id: run.snapshot() for run_id, run in RUNS.items()}
            return _json_response(self, 200, {"runs": runs})

        if len(parts) == 3 and parts[:2] == ["api", "runs"]:
            run_id = parts[2]
            with RUNS_LOCK:
                run = RUNS.get(run_id)
            if not run:
                return _json_response(self, 404, {"error": "run not found"})
            return _json_response(self, 200, {"run_id": run_id, "snapshot": run.snapshot()})

        if parsed.path == "/":
            return _serve_file(self, WEB_ROOT / "index.html")

        relative = parsed.path.lstrip("/")
        return _serve_file(self, WEB_ROOT / relative)

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        body = _read_json(self)

        if parsed.path == "/api/preview":
            csv_text = body.get("csv_text", "")
            if not csv_text.strip():
                return _json_response(self, 400, {"error": "csv_text is required"})
            preview = preview_csv(
                csv_text,
                scale=float(body.get("scale", 1.0)),
                gap_compression_seconds=int(body.get("gap_compression_seconds", 300)),
            )
            return _json_response(self, 200, preview)

        if parsed.path == "/api/runs":
            csv_text = body.get("csv_text", "")
            if not csv_text.strip():
                return _json_response(self, 400, {"error": "csv_text is required"})

            run_id = uuid.uuid4().hex[:12]
            runner = BenchmarkRunner(
                csv_text=csv_text,
                concurrency_target=int(body.get("concurrency_target", 80)),
                test_duration=int(body.get("test_duration", 300)),
                scale=float(body.get("scale", 1.0)),
                gap_compression_seconds=int(body.get("gap_compression_seconds", 300)),
                submission_workers=int(body.get("submission_workers", 20)),
            )
            with RUNS_LOCK:
                RUNS[run_id] = runner
            runner.start()
            return _json_response(self, 201, {"run_id": run_id, "snapshot": runner.snapshot()})

        if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "cancel":
            run_id = parts[2]
            with RUNS_LOCK:
                run = RUNS.get(run_id)
            if not run:
                return _json_response(self, 404, {"error": "run not found"})
            run.cancel()
            return _json_response(self, 200, {"ok": True, "snapshot": run.snapshot()})

        return _json_response(self, 404, {"error": "unknown endpoint"})


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster SAT dashboard server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"Serving on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()