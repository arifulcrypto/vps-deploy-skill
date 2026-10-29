"""Shared fixtures: a 3X-UI-like SQLite schema (modelled on v3.11.0) and a scripted fake remote."""
import json
import sqlite3
import subprocess
import sys

import pytest

SCHEMA = """
CREATE TABLE settings (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, value TEXT);
CREATE INDEX idx_settings_key ON settings(key);
CREATE TABLE inbounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, up INTEGER, down INTEGER, total INTEGER,
    remark TEXT, sub_sort_index INTEGER DEFAULT 1, exclude_from_sub NUMERIC DEFAULT false, enable NUMERIC,
    expiry_time INTEGER, traffic_reset TEXT DEFAULT 'never', traffic_reset_day INTEGER DEFAULT 1,
    last_traffic_reset_time INTEGER DEFAULT 0, listen TEXT, port INTEGER, protocol TEXT, settings TEXT,
    stream_settings TEXT, tag TEXT UNIQUE, sniffing TEXT, node_id INTEGER,
    share_addr_strategy TEXT DEFAULT 'node', share_addr TEXT, disable_flow NUMERIC DEFAULT false,
    origin_node_guid TEXT
);
CREATE TABLE clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, sub_id TEXT, uuid TEXT, password TEXT,
    auth TEXT, flow TEXT, security TEXT, reverse TEXT, limit_ip INTEGER, limit_hwid INTEGER DEFAULT 0,
    total_gb INTEGER, expiry_time INTEGER, enable NUMERIC DEFAULT true, tg_id INTEGER, group_name TEXT DEFAULT '',
    comment TEXT, reset INTEGER DEFAULT 0, reset_day INTEGER DEFAULT 0, reset_weekday INTEGER DEFAULT 0,
    reset_max INTEGER DEFAULT 0, traffic_reset TEXT DEFAULT 'never', traffic_reset_day INTEGER DEFAULT 1,
    created_at INTEGER, updated_at INTEGER, sync_orphaned_at INTEGER DEFAULT 0
);
CREATE TABLE client_inbounds (
    client_id INTEGER, inbound_id INTEGER, flow_override TEXT, created_at INTEGER,
    PRIMARY KEY (client_id, inbound_id)
);
"""


@pytest.fixture
def xui_db(tmp_path):
    path = tmp_path / "x-ui.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO settings (key, value) VALUES (?, ?)", [
        ("twoFactorEnable", "true"), ("twoFactorToken", "SECRET2FA"),
        ("webCertFile", "/etc/ssl/panel.pem"), ("webDomain", "panel.example.org"),
    ])
    conn.execute("INSERT INTO clients (id, email, uuid, sub_id) VALUES (77, 'customer@example.com', 'cust-uuid', 'cust')")
    conn.execute(
        "INSERT INTO inbounds (id, remark, enable, port, protocol, settings, stream_settings, tag) "
        "VALUES (5, 'customer', 1, 19000, 'vless', ?, '{\"network\":\"tcp\"}', 'inbound-19000')",
        (json.dumps({"clients": [{"id": "cust-uuid", "email": "customer@example.com"}]}),))
    conn.commit()
    conn.close()
    return str(path)


def run_db_script(payload):
    from scripts.db_configurator import REMOTE_DB_SCRIPT
    res = subprocess.run([sys.executable, "-c", REMOTE_DB_SCRIPT], input=json.dumps(payload),
                         capture_output=True, text=True)
    out = json.loads(res.stdout.strip().splitlines()[-1]) if res.stdout.strip() else {}
    return res.returncode, out


class FakeRemote:
    """Scripted stand-in for SSHTarget: responses are keyed by step name."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def _reply(self, name, payload=None):
        self.calls.append((name, payload))
        rc, out, err = self.responses.get(name, (0, "", ""))
        if callable(out):
            out = out(payload)
        return subprocess.CompletedProcess([name], rc, out, err)

    def run(self, command, input=None, timeout=120, check=True, name="remote command"):
        res = self._reply(name, input)
        if check and res.returncode != 0:
            from scripts.remote import DeploymentError
            raise DeploymentError(f"{name} failed (exit {res.returncode}): {res.stderr}")
        return res

    def run_script(self, name, script, timeout=180, check=True):
        return self.run("bash -s", input=script, check=check, name=name)

    def run_python(self, name, script, payload, timeout=60, check=True):
        return self.run("python3", input=json.dumps(payload), check=check, name=name)


@pytest.fixture
def fake_remote_factory():
    return FakeRemote
