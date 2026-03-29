
"""HTTP UI + JSON API for ffmpeg-http-browser."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlparse

if TYPE_CHECKING:
    from .browse_app import BrowserApp


def _json_bytes(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


class WebUIHandler(BaseHTTPRequestHandler):
    app: "BrowserApp" = None  # type: ignore
    static_dir: Path = None  # type: ignore

    def log_message(self, format, *args):
        line = "%s - - [%s] %s" % (
            self.address_string(),
            self.log_date_time_string(),
            format % args,
        )
        line += chr(10)
        sys.stderr.write(line)

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, obj) -> None:
        self._send(code, _json_bytes(obj), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/":
            index_path = type(self).static_dir / "index.html"
            if not index_path.is_file():
                self._send_json(500, {"error": "missing index.html"})
                return
            body = index_path.read_bytes()
            self._send(200, body, "text/html; charset=utf-8")
            return
        if path == "/api/browse":
            qs = parse_qs(parsed.query)
            raw = qs.get("path", [""])[0]
            rel = unquote(raw).replace(chr(92), "/")
            data = type(self).app.list_browse(rel)
            self._send_json(200, data)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") != "/api/play":
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return
        rel = payload.get("path") or ""
        if not isinstance(rel, str):
            self._send_json(400, {"error": "path must be string"})
            return
        host = self.headers.get("Host", "").split(":")[0] or None
        data, err = type(self).app.play(rel.replace(chr(92), "/"), host)
        if err:
            self._send_json(400, {"error": err})
            return
        self._send_json(200, data)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "streams":
            sid = parts[2]
            ok, err = type(self).app.stop_stream(sid)
            if not ok:
                self._send_json(404, {"error": err or "not found"})
                return
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"error": "not found"})


def run_web_server(app: "BrowserApp", bind_host: str, port: int) -> tuple:
    static_dir = Path(__file__).resolve().parent / "static"
    WebUIHandler.app = app
    WebUIHandler.static_dir = static_dir
    server = HTTPServer((bind_host, port), WebUIHandler)
    thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
