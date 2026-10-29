"""Run the panel probe against a fake 3X-UI panel that enforces session-bound CSRF tokens."""
import json
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from scripts.panel_probe import REMOTE_PROBE_SCRIPT

BASE = "/secret/"


class FakePanel(BaseHTTPRequestHandler):
    sessions = {}

    def log_message(self, *args):
        pass

    def _sid(self):
        cookie = self.headers.get("Cookie", "")
        return cookie.split("sid=")[1].split(";")[0] if "sid=" in cookie else None

    def _json(self, obj, cookie=None):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if cookie:
            self.send_header("Set-Cookie", f"sid={cookie}; Path=/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        sid = self._sid()
        if self.path == BASE:
            new = sid or f"s{len(self.sessions)}"
            self.sessions.setdefault(new, {"csrf": f"tok-{new}", "auth": False})
            return self._json({}, cookie=new)
        if self.path == BASE + "csrf-token" and sid in self.sessions:
            return self._json({"success": True, "obj": self.sessions[sid]["csrf"]})
        if self.path == BASE + "panel/api/inbounds/list" and sid in self.sessions and self.sessions[sid]["auth"]:
            return self._json({"success": True, "obj": []})
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        sid = self._sid()
        data = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        if self.path != BASE + "login" or sid not in self.sessions:
            self.send_response(404)
            self.end_headers()
            return
        if self.headers.get("X-CSRF-Token") != self.sessions[sid]["csrf"]:
            self.send_response(403)
            self.end_headers()
            return
        ok = data.get("username") == ["admin"] and data.get("password") == ["Pa'ss\"word"]
        self.sessions[sid]["auth"] = ok
        self._json({"success": ok, "msg": "" if ok else "wrong credentials"})


@pytest.fixture
def panel():
    server = HTTPServer(("127.0.0.1", 0), FakePanel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


def probe(port, password):
    payload = {"port": port, "base_path": BASE, "user": "admin", "password": password, "host": None}
    res = subprocess.run([sys.executable, "-c", REMOTE_PROBE_SCRIPT], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
    return res.returncode, json.loads(res.stdout.strip().splitlines()[-1])


def test_probe_succeeds_with_csrf_and_verifies_api(panel):
    rc, out = probe(panel, "Pa'ss\"word")
    assert rc == 0 and out["ok"] and out["scheme"] == "http" and out["api_verified"]


def test_probe_fails_closed_on_wrong_password(panel):
    rc, out = probe(panel, "wrong")
    assert rc == 1 and not out["ok"] and out["stage"] == "login"


def test_probe_reports_connection_failure():
    rc, out = probe(1, "x")
    assert rc == 1 and out["stage"] == "connect"
