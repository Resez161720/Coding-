"""เว็บเซิร์ฟเวอร์ในเครื่อง (ไม่ต้องติดตั้งเพิ่ม) สำหรับหน้าจอของคนพิมพ์ tag"""

import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .store import StoreError

log = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8"}
REQUEST_ACTION = re.compile(r"^/api/requests/(\d+)/(edit|cancel|retry|resolve)$")


class Handler(BaseHTTPRequestHandler):
    app = None
    local_only = True

    def log_message(self, format, *args):
        log.debug("%s - %s", self.address_string(), format % args)

    def _send(self, status, body: bytes, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status=200):
        self._send(status, json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _host_allowed(self):
        if not self.local_only:
            return True
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ("127.0.0.1", "localhost")

    def do_GET(self):
        if not self._host_allowed():
            return self._json({"error": "forbidden"}, 403)
        path = urlparse(self.path).path
        if path == "/":
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path == "/api/state":
            return self._json(self.app.state())
        if path == "/cards":
            return self._send(200, self.app.cards_html().encode("utf-8"), CONTENT_TYPES[".html"])
        return self._json({"error": "not found"}, 404)

    def _static(self, name):
        file = STATIC / name
        if "/" in name or "\\" in name or not file.is_file():
            return self._json({"error": "not found"}, 404)
        self._send(200, file.read_bytes(), CONTENT_TYPES.get(file.suffix, "application/octet-stream"))

    def do_POST(self):
        # หัวข้อ X-Tagbot ป้องกันเว็บอื่นในเบราว์เซอร์เดียวกันส่งคำสั่งมาที่โปรแกรมนี้
        if not self._host_allowed() or self.headers.get("X-Tagbot") != "1":
            return self._json({"error": "forbidden"}, 403)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except json.JSONDecodeError:
            return self._json({"error": "ข้อมูลที่ส่งมาไม่ใช่ JSON"}, 400)
        try:
            return self._json(self._route(urlparse(self.path).path, body))
        except (ValueError, StoreError) as error:
            return self._json({"error": str(error)}, 400)
        except LookupError:
            return self._json({"error": "not found"}, 404)
        except Exception as error:
            log.exception("POST %s failed", self.path)
            return self._json({"error": f"ผิดพลาด: {error}"}, 500)

    def _route(self, path, body):
        app = self.app
        match = REQUEST_ACTION.match(path)
        if match:
            request_id, action = int(match.group(1)), match.group(2)
            if action == "edit":
                app.edit(request_id, body)
            else:
                getattr(app, action)(request_id)
            return {"ok": True}
        if path == "/api/import":
            return app.import_scans(str(body.get("text", "")), force=bool(body.get("force")))
        if path == "/api/wo-color":
            app.set_wo_color(str(body.get("work_order", "")), str(body.get("color", "")))
            return {"ok": True}
        if path == "/api/run":
            ok, message = app.start_run(str(body.get("color", "")))
            return {"ok": ok, "message": message}
        if path == "/api/stop":
            app.stop()
            return {"ok": True}
        if path == "/api/answer":
            return {"ok": app.answer(int(body.get("id", 0)), bool(body.get("yes")))}
        if path == "/api/dump":
            return {"path": str(app.dump_screen())}
        if path == "/api/reload":
            return {"error": app.reload_master()}
        raise LookupError(path)


def make_server(app, host, port) -> ThreadingHTTPServer:
    handler = type("TagbotHandler", (Handler,), {"app": app, "local_only": host in ("127.0.0.1", "localhost")})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
