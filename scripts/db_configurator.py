#!/usr/bin/env python3
"""
3X-UI SQLite Database Provisioner:
Builds inbound specifications locally and applies them with a static remote script
(payload via stdin). Ownership is explicit: only rows tagged `vps-skill-*` and the
client whose email is `vps-skill-<deploy_id>` are ever modified. Port conflicts with
foreign inbounds abort before any write; the database is backed up first and all
writes happen in a single transaction.
"""
from typing import Any, Dict, List, Optional

TAG_PREFIX = "vps-skill-"
DEFAULT_DB_PATH = "/etc/x-ui/x-ui.db"

SNIFFING = {"enabled": True, "destOverride": ["http", "tls", "quic", "fakedns"], "routeOnly": False}


def _tls_settings(server_name: str, cert_path: str, key_path: str, alpn: List[str]) -> Dict[str, Any]:
    return {
        "serverName": server_name,
        "minVersion": "1.2",
        "maxVersion": "1.3",
        "cipherSuites": "",
        "rejectUnknownSni": False,
        "disableSystemRoot": False,
        "enableSessionResumption": False,
        "certificates": [{
            "ocspStapling": 0,
            "oneTimeLoading": False,
            "usage": "encipherment",
            "buildChain": False,
            "certificateFile": cert_path,
            "keyFile": key_path,
        }],
        "alpn": alpn,
    }


def _client(identity: Dict[str, str], **extra) -> Dict[str, Any]:
    entry = {
        "id": identity["uuid"],
        "email": identity["email"],
        "subId": identity["sub_id"],
        "enable": True,
        "expiryTime": 0,
        "limitIp": 0,
        "totalGB": 0,
        "tgId": 0,
        "reset": 0,
        "trafficReset": "never",
        "trafficResetDay": 1,
    }
    entry.update(extra)
    return entry


def ws_inbound(identity, port: int, domain: str, ws_path: str, cert_path: str, key_path: str) -> Dict[str, Any]:
    return {
        "tag": f"{TAG_PREFIX}cf-vless",
        "port": port,
        "transport": "tcp",
        "protocol": "vless",
        "remark": "vps-skill-cdn-ws",
        "settings": {"decryption": "none"},
        "client": _client(identity, flow=""),
        "stream": {
            "network": "ws",
            "security": "tls",
            "tlsSettings": _tls_settings(domain, cert_path, key_path, ["http/1.1"]),
            "wsSettings": {"acceptProxyProtocol": False, "path": ws_path, "headers": {}},
        },
    }


def hy2_inbound(identity, port: int, server_name: str, cert_path: str, key_path: str,
                obfs_password: Optional[str]) -> Dict[str, Any]:
    stream: Dict[str, Any] = {
        "network": "hysteria",
        "hysteriaSettings": {
            "version": 2,
            "udpIdleTimeout": 60,
            "masquerade": {"type": "", "dir": "", "url": "", "rewriteHost": False, "insecure": False,
                           "content": "", "headers": {}, "statusCode": 0},
        },
        "security": "tls",
        "tlsSettings": _tls_settings(server_name, cert_path, key_path, ["h3"]),
        "finalmask": {
            "quicParams": {
                "congestion": "bbr",
                "debug": False,
                "initStreamReceiveWindow": 8388608,
                "maxStreamReceiveWindow": 8388608,
                "initConnectionReceiveWindow": 20971520,
                "maxConnectionReceiveWindow": 20971520,
                "maxIdleTimeout": 30,
                "keepAlivePeriod": 10,
                "disablePathMTUDiscovery": False,
                "maxIncomingStreams": 1024,
            },
        },
    }
    if obfs_password:
        stream["finalmask"]["udp"] = [{"type": "salamander", "settings": {"password": obfs_password}}]
    return {
        "tag": f"{TAG_PREFIX}hy2",
        "port": port,
        "transport": "udp",
        "protocol": "hysteria",
        "remark": "vps-skill-hy2",
        "settings": {"version": 2},
        "client": _client(identity, auth=identity["node_pass"], password=identity["node_pass"]),
        "stream": stream,
    }


def reality_inbound(identity, port: int, target: str, server_names: List[str], private_key: str,
                    public_key: str, short_id: str, xver: int = 0) -> Dict[str, Any]:
    return {
        "tag": f"{TAG_PREFIX}reality",
        "port": port,
        "transport": "tcp",
        "protocol": "vless",
        "remark": "vps-skill-reality",
        "settings": {"decryption": "none", "encryption": "none"},
        "client": _client(identity, flow="xtls-rprx-vision"),
        "stream": {
            "network": "tcp",
            "tcpSettings": {"acceptProxyProtocol": False, "header": {"type": "none"}},
            "security": "reality",
            "realitySettings": {
                "show": False,
                "xver": xver,
                "target": target,
                "serverNames": server_names,
                "privateKey": private_key,
                "minClientVer": "1.8.0",
                "maxClientVer": "",
                "maxTimediff": 0,
                "shortIds": [short_id],
                "settings": {"publicKey": public_key, "fingerprint": "chrome", "serverName": "", "spiderX": ""},
            },
        },
    }


def build_db_payload(identity: Dict[str, str], inbounds: List[Dict[str, Any]], settings: Dict[str, str],
                     db_path: str = DEFAULT_DB_PATH, backup: bool = True) -> Dict[str, Any]:
    return {
        "db_path": db_path,
        "tag_prefix": TAG_PREFIX,
        "identity": {k: identity[k] for k in ("email", "uuid", "sub_id", "node_pass")},
        "inbounds": inbounds,
        "settings": settings,
        "backup": backup,
        "sniffing": SNIFFING,
    }


# Static remote script: reads the JSON payload from stdin, never interpolated.
REMOTE_DB_SCRIPT = r'''
import glob, json, os, sqlite3, sys, time

cfg = json.load(sys.stdin)
db_path = cfg["db_path"]
prefix = cfg["tag_prefix"]
ident = cfg["identity"]
UDP_PROTOCOLS = {"hysteria", "hysteria2", "tuic", "wireguard", "amneziawg", "masque"}


def finish(obj, code=0):
    print(json.dumps(obj))
    sys.exit(code)


if not os.path.exists(db_path):
    finish({"ok": False, "error": "database not found: " + db_path}, 2)

conn = sqlite3.connect(db_path, timeout=30)
conn.isolation_level = None
c = conn.cursor()


def columns(table):
    return {r[1] for r in c.execute("PRAGMA table_info(%s)" % table).fetchall()}


tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
missing = {"inbounds", "settings"} - tables
if missing:
    finish({"ok": False, "error": "unsupported 3X-UI schema, missing tables: %s" % sorted(missing)}, 2)
inbound_cols = columns("inbounds")
need = {"id", "port", "protocol", "settings", "stream_settings", "tag", "enable"}
if need - inbound_cols:
    finish({"ok": False, "error": "unsupported inbounds schema, missing columns: %s" % sorted(need - inbound_cols)}, 2)


def owned(tag):
    return (tag or "").startswith(prefix)


def transport(protocol, stream_str):
    if protocol in UDP_PROTOCOLS:
        return "udp"
    try:
        network = json.loads(stream_str or "{}").get("network")
    except ValueError:
        network = None
    return "udp" if network == "kcp" else "tcp"


# 1. Refuse to touch anything if a foreign, enabled inbound already uses a planned port/transport.
conflicts = []
for spec in cfg["inbounds"]:
    rows = c.execute("SELECT id, tag, protocol, stream_settings FROM inbounds WHERE port = ? AND enable = 1",
                     (spec["port"],)).fetchall()
    for rid, tag, protocol, stream in rows:
        if not owned(tag) and transport(protocol, stream) == spec["transport"]:
            conflicts.append({"id": rid, "tag": tag, "port": spec["port"], "transport": spec["transport"]})
if conflicts:
    finish({"ok": False, "error": "port conflict with existing inbounds", "conflicts": conflicts}, 3)

# 2. Consistent backup (online backup API), keep the five most recent.
backup_path = None
if cfg.get("backup", True):
    backup_path = "%s.vps-skill-%d.bak" % (db_path, int(time.time()))
    dst = sqlite3.connect(backup_path)
    conn.backup(dst)
    dst.close()
    os.chmod(backup_path, 0o600)
    for old in sorted(glob.glob(db_path + ".vps-skill-*.bak"))[:-5]:
        os.remove(old)

now_ms = int(time.time() * 1000)


def set_setting(key, value):
    # settings.key is not unique in 3X-UI and the panel reads the first row:
    # update every existing row instead of appending a duplicate.
    if c.execute("SELECT 1 FROM settings WHERE key = ?", (key,)).fetchone():
        c.execute("UPDATE settings SET value = ? WHERE key = ?", (value, key))
    else:
        c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))


def insert_row(table, values):
    cols = [k for k in values if k in columns(table)]
    c.execute("INSERT INTO %s (%s) VALUES (%s)" % (table, ", ".join(cols), ", ".join("?" * len(cols))),
              [values[k] for k in cols])
    return c.lastrowid


def merged_settings(spec, existing_str):
    try:
        existing = json.loads(existing_str or "{}")
    except ValueError:
        existing = {}
    clients = [cl for cl in existing.get("clients", []) if cl.get("email") != ident["email"]]
    ours = dict(spec["client"], created_at=now_ms, updated_at=now_ms)
    settings = dict(spec["settings"])
    settings["clients"] = clients + [ours]
    return json.dumps(settings, indent=2)


result = {"ok": True, "inbounds": {}, "disabled_stale": [], "backup": backup_path}
try:
    c.execute("BEGIN")
    for key, value in cfg["settings"].items():
        set_setting(key, value)

    client_id = None
    if "clients" in tables:
        row = c.execute("SELECT id FROM clients WHERE email = ?", (ident["email"],)).fetchone()
        fields = {"uuid": ident["uuid"], "sub_id": ident["sub_id"], "password": ident["node_pass"],
                  "auth": ident["node_pass"], "updated_at": now_ms}
        if row:
            client_id = row[0]
            sets = [k for k in fields if k in columns("clients")]
            c.execute("UPDATE clients SET %s WHERE id = ?" % ", ".join(k + " = ?" for k in sets),
                      [fields[k] for k in sets] + [client_id])
        else:
            client_id = insert_row("clients", dict(fields, email=ident["email"], flow="", security="auto",
                                                   reverse="", limit_ip=0, limit_hwid=0, total_gb=0,
                                                   expiry_time=0, enable=1, tg_id=0, group_name="",
                                                   comment="", reset=0, reset_day=0, reset_weekday=0,
                                                   reset_max=0, traffic_reset="never", traffic_reset_day=1,
                                                   created_at=now_ms, sync_orphaned_at=0))

    for spec in cfg["inbounds"]:
        stream = json.dumps(spec["stream"])
        row = c.execute("SELECT id, settings FROM inbounds WHERE tag = ?", (spec["tag"],)).fetchone()
        if row:
            inbound_id = row[0]
            c.execute("UPDATE inbounds SET port = ?, protocol = ?, remark = ?, settings = ?, stream_settings = ?, "
                      "enable = 1 WHERE id = ?",
                      (spec["port"], spec["protocol"], spec["remark"], merged_settings(spec, row[1]), stream,
                       inbound_id))
        else:
            inbound_id = insert_row("inbounds", {
                "user_id": 1, "up": 0, "down": 0, "total": 0, "remark": spec["remark"], "sub_sort_index": 1,
                "exclude_from_sub": 0, "enable": 1, "expiry_time": 0, "traffic_reset": "never",
                "traffic_reset_day": 1, "last_traffic_reset_time": 0, "listen": "", "port": spec["port"],
                "protocol": spec["protocol"], "settings": merged_settings(spec, None), "stream_settings": stream,
                "tag": spec["tag"], "sniffing": json.dumps(cfg["sniffing"]), "node_id": None,
                "share_addr_strategy": "node", "share_addr": "", "disable_flow": 0, "origin_node_guid": "",
            })
        result["inbounds"][spec["tag"]] = inbound_id
        if client_id is not None and "client_inbounds" in tables:
            link_cols = columns("client_inbounds")
            flow_val = spec.get("client", {}).get("flow", "")
            link = {"client_id": client_id, "inbound_id": inbound_id, "flow_override": flow_val, "created_at": now_ms}
            cols = [k for k in link if k in link_cols]
            c.execute("INSERT OR REPLACE INTO client_inbounds (%s) VALUES (%s)" % (", ".join(cols), ", ".join("?" * len(cols))),
                      [link[k] for k in cols])

    # Disable only skill-owned inbounds that are no longer part of the plan (e.g. after a profile switch).
    planned = {spec["tag"] for spec in cfg["inbounds"]}
    for rid, tag in c.execute("SELECT id, tag FROM inbounds WHERE enable = 1").fetchall():
        if owned(tag) and tag not in planned:
            c.execute("UPDATE inbounds SET enable = 0 WHERE id = ?", (rid,))
            result["disabled_stale"].append(tag)
    c.execute("COMMIT")
except Exception as exc:
    c.execute("ROLLBACK")
    finish({"ok": False, "error": "database update failed and was rolled back: %r" % (exc,)}, 4)

finish(result)
'''
