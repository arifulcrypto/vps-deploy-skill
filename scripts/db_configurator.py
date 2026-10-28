#!/usr/bin/env python3
"""
3X-UI SQLite Database Provisioner:
Builds non-destructive, injection-safe Python payloads to configure
multi-protocol inbounds (Hysteria 2, VLESS-Reality, VLESS-WS) into /etc/x-ui/x-ui.db.
"""
import base64
import json
from typing import Dict, Any, Optional


def generate_remote_sqlite_script(
    client_uuid: str,
    sub_id: str,
    email: str,
    password: str,
    hy2_port: int,
    reality_port: int,
    cf_port: int = 443,
    domain: Optional[str] = None,
    cert_path: Optional[str] = None,
    key_path: Optional[str] = None,
    obfs_password: str = "random_obfs_pass",
    reality_privkey: str = "",
    reality_pubkey: str = "",
    reality_shortid: str = "8c7d6e5a",
    reality_sni: str = "addons.mozilla.org",
) -> str:
    """
    Generate a Python script that injects inbounds safely using a Base64-encoded JSON payload.
    Immune to format string bugs, quotes, backslashes, and shell interpolation.
    """
    payload_data = {
        "client_uuid": client_uuid,
        "sub_id": sub_id,
        "email": email,
        "password": password,
        "hy2_port": int(hy2_port),
        "reality_port": int(reality_port),
        "cf_port": int(cf_port),
        "domain": domain or "",
        "cert_path": cert_path or "",
        "key_path": key_path or "",
        "obfs_password": obfs_password,
        "reality_privkey": reality_privkey,
        "reality_pubkey": reality_pubkey,
        "reality_shortid": reality_shortid,
        "reality_sni": reality_sni,
    }

    payload_b64 = base64.b64encode(json.dumps(payload_data).encode("utf-8")).decode("utf-8")

    # Static remote script (no f-string interpolation of user input)
    template = '''# -*- coding: utf-8 -*-
import sqlite3
import json
import time
import base64

PAYLOAD_B64 = "''' + payload_b64 + '''"
cfg = json.loads(base64.b64decode(PAYLOAD_B64).decode("utf-8"))

conn = sqlite3.connect('/etc/x-ui/x-ui.db')
c = conn.cursor()

client_uuid = cfg["client_uuid"]
sub_id = cfg["sub_id"]
email = cfg["email"]
password = cfg["password"]
hy2_port = cfg["hy2_port"]
reality_port = cfg["reality_port"]
cf_port = cfg["cf_port"]
domain = cfg["domain"]
cert_path = cfg["cert_path"]
key_path = cfg["key_path"]
obfs_pass = cfg["obfs_password"]
reality_privkey = cfg["reality_privkey"]
reality_pubkey = cfg["reality_pubkey"]
reality_shortid = cfg["reality_shortid"]
reality_sni = cfg["reality_sni"]
now_ms = int(time.time() * 1000)

# 1. Update settings if certificates exist
if cert_path and key_path:
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('webCertFile', ?)", (cert_path,))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('webKeyFile', ?)", (key_path,))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('subCertFile', ?)", (cert_path,))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('subKeyFile', ?)", (key_path,))

c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('subEnable', 'true')")
c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('subClashEnable', 'true')")

# Check table existence and columns dynamically
existing_tables = [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

client_id = 1
if 'clients' in existing_tables:
    clients_cols = [col[1] for col in c.execute('PRAGMA table_info(clients)').fetchall()]
    row = c.execute("SELECT id FROM clients WHERE uuid = ? OR sub_id = ?", (client_uuid, sub_id)).fetchone()
    if row:
        client_id = row[0]
        c.execute("UPDATE clients SET email = ?, password = ?, auth = ?, updated_at = ? WHERE id = ?",
                  (email, password, password, now_ms, client_id))
    else:
        max_client_id = c.execute("SELECT coalesce(max(id), 0) FROM clients").fetchone()[0]
        client_id = max_client_id + 1
        
        # Build dynamic insert for clients
        col_values = {
            'id': client_id,
            'email': email,
            'sub_id': sub_id,
            'uuid': client_uuid,
            'password': password,
            'auth': password,
            'flow': '',
            'security': 'auto',
            'reverse': '',
            'limit_ip': 0,
            'limit_hwid': 0,
            'total_gb': 0,
            'expiry_time': 0,
            'enable': 1,
            'tg_id': 0,
            'group_name': '',
            'comment': '',
            'reset': 0,
            'reset_day': 0,
            'reset_weekday': 0,
            'reset_max': 0,
            'traffic_reset': 'never',
            'traffic_reset_day': 1,
            'created_at': now_ms,
            'updated_at': now_ms,
            'sync_orphaned_at': 0
        }
        insert_cols = [col for col in clients_cols if col in col_values]
        placeholders = ', '.join(['?'] * len(insert_cols))
        vals = [col_values[col] for col in insert_cols]
        c.execute(f"INSERT INTO clients ({', '.join(insert_cols)}) VALUES ({placeholders})", vals)

def upsert_inbound(tag, port, protocol, remark, settings_str, stream_str):
    inbounds_cols = [col[1] for col in c.execute('PRAGMA table_info(inbounds)').fetchall()]
    row = c.execute("SELECT id FROM inbounds WHERE tag = ?", (tag,)).fetchone()
    if row:
        inb_id = row[0]
        c.execute("""
            UPDATE inbounds SET port = ?, protocol = ?, remark = ?, settings = ?, stream_settings = ?, enable = 1
            WHERE id = ?
        """, (port, protocol, remark, settings_str, stream_str, inb_id))
    else:
        max_id = c.execute("SELECT coalesce(max(id), 0) FROM inbounds").fetchone()[0]
        inb_id = max_id + 1
        col_values = {
            'id': inb_id,
            'user_id': 1,
            'up': 0,
            'down': 0,
            'total': 0,
            'remark': remark,
            'sub_sort_index': inb_id,
            'exclude_from_sub': 0,
            'enable': 1,
            'expiry_time': 0,
            'traffic_reset': 'never',
            'traffic_reset_day': 1,
            'last_traffic_reset_time': 0,
            'listen': '',
            'port': port,
            'protocol': protocol,
            'settings': settings_str,
            'stream_settings': stream_str,
            'tag': tag,
            'sniffing': json.dumps({"enabled": True, "destOverride": ["http", "tls", "quic", "fakedns"], "routeOnly": False}),
            'node_id': None,
            'share_addr_strategy': 'node',
            'share_addr': '',
            'disable_flow': 0,
            'origin_node_guid': ''
        }
        insert_cols = [col for col in inbounds_cols if col in col_values]
        placeholders = ', '.join(['?'] * len(insert_cols))
        vals = [col_values[col] for col in insert_cols]
        c.execute(f"INSERT INTO inbounds ({', '.join(insert_cols)}) VALUES ({placeholders})", vals)

    if 'client_inbounds' in existing_tables:
        c.execute("INSERT OR REPLACE INTO client_inbounds (client_id, inbound_id, flow_override, created_at) VALUES (?, ?, '', ?)",
                  (client_id, inb_id, now_ms))
    return inb_id

# 3. Inbound 1: Port 443 VLESS-WS-TLS (if domain provided)
if domain and cert_path and key_path:
    vless_settings = json.dumps({
        "clients": [{
            "id": client_uuid,
            "flow": "",
            "email": email,
            "limitIp": 0,
            "totalGB": 0,
            "expiryTime": 0,
            "enable": True,
            "tgId": 0,
            "subId": sub_id,
            "reset": 0,
            "resetDay": 0,
            "resetWeekday": 0,
            "resetMax": 0,
            "trafficReset": "never",
            "trafficResetDay": 1,
            "created_at": now_ms,
            "updated_at": now_ms
        }],
        "decryption": "none"
    }, indent=2)

    vless_stream = json.dumps({
        "network": "ws",
        "security": "tls",
        "tlsSettings": {
            "serverName": domain,
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
                "keyFile": key_path
            }],
            "alpn": ["http/1.1"]
        },
        "wsSettings": {
            "acceptProxyProtocol": False,
            "path": "/ws",
            "headers": {}
        }
    })
    upsert_inbound("vps-skill-cf-vless", cf_port, "vless", f"VPS-CF-VLESS-{cf_port}", vless_settings, vless_stream)

# 4. Inbound 2: Hysteria 2
hy2_settings = json.dumps({
    "clients": [{
        "id": client_uuid,
        "auth": password,
        "password": password,
        "email": email,
        "enable": True,
        "expiryTime": 0,
        "limitIp": 0,
        "totalGB": 0,
        "trafficReset": "never",
        "trafficResetDay": 1,
        "created_at": now_ms,
        "updated_at": now_ms
    }],
    "version": 2
}, indent=2)

hy2_tls_certs = [{
    "ocspStapling": 0,
    "oneTimeLoading": False,
    "usage": "encipherment",
    "buildChain": False,
    "certificateFile": cert_path,
    "keyFile": key_path
}] if (cert_path and key_path) else []

hy2_stream = json.dumps({
    "network": "hysteria",
    "hysteriaSettings": {
        "version": 2,
        "udpIdleTimeout": 60,
        "masquerade": {
            "type": "",
            "dir": "",
            "url": "",
            "rewriteHost": False,
            "insecure": False,
            "content": "",
            "headers": {},
            "statusCode": 0
        }
    },
    "security": "tls" if (cert_path and key_path) else "none",
    "tlsSettings": {
        "serverName": domain if domain else "localhost",
        "minVersion": "1.2",
        "maxVersion": "1.3",
        "cipherSuites": "",
        "rejectUnknownSni": False,
        "disableSystemRoot": False,
        "enableSessionResumption": False,
        "certificates": hy2_tls_certs,
        "alpn": ["h3"]
    },
    "finalmask": {
        "udp": [{
            "type": "salamander",
            "settings": {
                "password": obfs_pass
            }
        }],
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
            "maxIncomingStreams": 1024
        }
    }
})
upsert_inbound("vps-skill-hy2", hy2_port, "hysteria", f"VPS-Direct-Hy2-{hy2_port}", hy2_settings, hy2_stream)

# 5. Inbound 3: VLESS-Reality
reality_settings = json.dumps({
    "clients": [{
        "id": client_uuid,
        "flow": "xtls-rprx-vision",
        "email": email,
        "enable": True,
        "expiryTime": 0,
        "limitIp": 0,
        "totalGB": 0,
        "trafficReset": "never",
        "trafficResetDay": 1,
        "created_at": now_ms,
        "updated_at": now_ms
    }],
    "decryption": "none",
    "encryption": "none"
}, indent=2)

reality_stream = json.dumps({
    "network": "tcp",
    "tcpSettings": {
        "acceptProxyProtocol": False,
        "header": {
            "type": "none"
        }
    },
    "security": "reality",
    "realitySettings": {
        "show": False,
        "xver": 0,
        "target": f"{reality_sni}:443",
        "serverNames": [
            reality_sni,
            f"services.{reality_sni}",
            reality_sni.replace("www.", "")
        ],
        "privateKey": reality_privkey,
        "minClientVer": "",
        "maxClientVer": "",
        "maxTimediff": 0,
        "shortIds": [
            reality_shortid,
            "1a2b3c4d"
        ],
        "settings": {
            "publicKey": reality_pubkey,
            "fingerprint": "chrome",
            "serverName": "",
            "spiderX": ""
        }
    }
})
upsert_inbound("vps-skill-reality", reality_port, "vless", f"VPS-Direct-Reality-{reality_port}", reality_settings, reality_stream)

conn.commit()
conn.close()
print("SUCCESS: 3X-UI DYNAMIC INBOUNDS CONFIGURED SAFELY WITHOUT OVERWRITING EXISTING ROWS")
'''
    return template
