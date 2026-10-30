"""Execute the generated DB script against a 3X-UI-like schema and check its side effects."""
import json
import sqlite3

from conftest import run_db_script
from scripts.db_configurator import build_db_payload, hy2_inbound, reality_inbound, ws_inbound

IDENTITY = {"email": "vps-skill-abcd1234", "uuid": "11111111-1111-1111-1111-111111111111",
            "sub_id": "s1", "node_pass": "pw_with\"quote'and\\slash"}


def payload(db, reality_port=20001, settings=None, inbounds=None):
    if inbounds is None:
        inbounds = [
            reality_inbound(IDENTITY, reality_port, "addons.mozilla.org:443", ["addons.mozilla.org"], "priv", "pub", "ab12"),
            hy2_inbound(IDENTITY, 30001, "198.51.100.1", "/c.pem", "/k.pem", "obfs"),
        ]
    return build_db_payload(IDENTITY, inbounds, settings if settings is not None else
                            {"webListen": "127.0.0.1"}, db_path=db)


def rows(db, sql, args=()):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def test_preserves_foreign_rows_and_security_settings(xui_db):
    rc, out = run_db_script(payload(xui_db))
    assert rc == 0 and out["ok"], out
    # unrelated inbound and client untouched
    assert rows(xui_db, "SELECT enable, tag FROM inbounds WHERE id = 5") == [(1, "inbound-19000")]
    assert rows(xui_db, "SELECT uuid, sub_id FROM clients WHERE id = 77") == [("cust-uuid", "cust")]
    # 2FA and panel TLS settings untouched
    settings = dict(rows(xui_db, "SELECT key, value FROM settings"))
    assert settings["twoFactorEnable"] == "true" and settings["twoFactorToken"] == "SECRET2FA"
    assert settings["webCertFile"] == "/etc/ssl/panel.pem"
    assert settings["webListen"] == "127.0.0.1"
    # backup written with owner-only permissions
    assert out["backup"] and oct(__import__("os").stat(out["backup"]).st_mode & 0o777) == "0o600"


def test_rerun_is_idempotent_and_never_duplicates_settings(xui_db):
    for _ in range(3):
        rc, out = run_db_script(payload(xui_db))
        assert rc == 0, out
    assert rows(xui_db, "SELECT count(*) FROM settings WHERE key = 'webListen'") == [(1,)]
    assert rows(xui_db, "SELECT count(*) FROM inbounds WHERE tag LIKE 'vps-skill-%'") == [(2,)]
    assert rows(xui_db, "SELECT count(*) FROM clients WHERE email = ?", (IDENTITY["email"],)) == [(1,)]
    # Check flow_override on client_inbounds
    inbound_id = rows(xui_db, "SELECT id FROM inbounds WHERE tag = 'vps-skill-reality'")[0][0]
    client_id = rows(xui_db, "SELECT id FROM clients WHERE email = ?", (IDENTITY["email"],))[0][0]
    assert rows(xui_db, "SELECT flow_override FROM client_inbounds WHERE client_id = ? AND inbound_id = ?",
                (client_id, inbound_id)) == [("xtls-rprx-vision",)]
    hy2 = json.loads(rows(xui_db, "SELECT settings FROM inbounds WHERE tag = 'vps-skill-hy2'")[0][0])
    assert [c["email"] for c in hy2["clients"]] == [IDENTITY["email"]]
    assert hy2["clients"][0]["auth"] == IDENTITY["node_pass"]


def test_existing_duplicate_settings_rows_are_all_updated(xui_db):
    conn = sqlite3.connect(xui_db)
    conn.executemany("INSERT INTO settings (key, value) VALUES ('webListen', ?)", [("",), ("0.0.0.0",)])
    conn.commit()
    conn.close()
    run_db_script(payload(xui_db))
    assert {v for (v,) in rows(xui_db, "SELECT value FROM settings WHERE key = 'webListen'")} == {"127.0.0.1"}


def test_foreign_port_conflict_aborts_without_changes(xui_db):
    rc, out = run_db_script(payload(xui_db, reality_port=19000))
    assert rc == 3 and not out["ok"]
    assert out["conflicts"][0]["tag"] == "inbound-19000"
    assert rows(xui_db, "SELECT count(*) FROM inbounds WHERE tag LIKE 'vps-skill-%'") == [(0,)]
    assert rows(xui_db, "SELECT count(*) FROM settings WHERE key = 'webListen'") == [(0,)]


def test_udp_inbound_does_not_conflict_with_tcp_on_same_port(xui_db):
    identity_inbounds = [hy2_inbound(IDENTITY, 19000, "198.51.100.1", "/c.pem", "/k.pem", None)]
    rc, out = run_db_script(payload(xui_db, inbounds=identity_inbounds))
    assert rc == 0, out


def test_manually_added_clients_in_owned_inbound_survive(xui_db):
    run_db_script(payload(xui_db))
    conn = sqlite3.connect(xui_db)
    settings = json.loads(conn.execute("SELECT settings FROM inbounds WHERE tag = 'vps-skill-reality'").fetchone()[0])
    settings["clients"].append({"id": "friend-uuid", "email": "friend"})
    conn.execute("UPDATE inbounds SET settings = ? WHERE tag = 'vps-skill-reality'", (json.dumps(settings),))
    conn.commit()
    conn.close()
    run_db_script(payload(xui_db))
    settings = json.loads(rows(xui_db, "SELECT settings FROM inbounds WHERE tag = 'vps-skill-reality'")[0][0])
    assert sorted(c["email"] for c in settings["clients"]) == sorted(["friend", IDENTITY["email"]])


def test_profile_switch_disables_only_stale_owned_inbounds(xui_db):
    ws = ws_inbound(IDENTITY, 443, "cdn.example.com", "/p", "/c.pem", "/k.pem")
    run_db_script(payload(xui_db, inbounds=[ws]))
    reality443 = reality_inbound(IDENTITY, 443, "127.0.0.1:8443", ["www.example.com"], "priv", "pub", "ab12", xver=1)
    rc, out = run_db_script(payload(xui_db, inbounds=[reality443]))
    assert rc == 0, out
    assert out["disabled_stale"] == ["vps-skill-cf-vless"]
    assert rows(xui_db, "SELECT enable FROM inbounds WHERE id = 5") == [(1,)]
    stream = json.loads(rows(xui_db, "SELECT stream_settings FROM inbounds WHERE tag = 'vps-skill-reality'")[0][0])
    assert stream["realitySettings"]["target"] == "127.0.0.1:8443"
    assert stream["realitySettings"]["xver"] == 1
    assert stream["realitySettings"]["shortIds"] == ["ab12"]


def test_missing_database_reports_error(tmp_path):
    rc, out = run_db_script(payload(str(tmp_path / "absent.db")))
    assert rc == 2 and "not found" in out["error"]
