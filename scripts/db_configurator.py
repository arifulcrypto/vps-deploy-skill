#!/usr/bin/env python3
"""
3X-UI SQLite Database Provisioner:
Generates self-contained Python script to inject multi-protocol inbounds
(VLESS-WS-TLS 443, Hysteria 2 UDP, VLESS-Reality TCP) with dynamic randomized ports
and adaptive schema handling.
"""
import json
import time
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
    Generate Python code to execute on the remote VPS for 3X-UI configuration.
    """
    script = f'''# Auto-generated 3X-UI dynamic multi-protocol injection script
import sqlite3
import json
import time

conn = sqlite3.connect('/etc/x-ui/x-ui.db')
c = conn.cursor()

client_uuid = "{client_uuid}"
sub_id = "{sub_id}"
email = "{email}"
password = "{password}"
hy2_port = {hy2_port}
reality_port = {reality_port}
cf_port = {cf_port}
domain = "{domain if domain else ''}"
cert_path = "{cert_path if cert_path else ''}"
key_path = "{key_path if key_path else ''}"
obfs_pass = "{obfs_password}"
reality_privkey = "{reality_privkey}"
reality_pubkey = "{reality_pubkey}"
reality_shortid = "{reality_shortid}"
reality_sni = "{reality_sni}"
now_ms = int(time.time() * 1000)

# Check table schema dynamically
inbounds_cols = [col[1] for col in c.execute('PRAGMA table_info(inbounds)').fetchall()]
has_exclude_from_sub = 'exclude_from_sub' in inbounds_cols

# 1. Mount SSL certificates and enable subscription features
if cert_path and key_path:
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('webCertFile', ?)", (cert_path,))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('webKeyFile', ?)", (key_path,))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('subCertFile', ?)", (cert_path,))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('subKeyFile', ?)", (key_path,))

c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('subEnable', 'true')")
c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('subClashEnable', 'true')")

# 2. Insert or update Client in clients table
c.execute("""
INSERT OR REPLACE INTO clients (
    id, email, sub_id, uuid, password, auth, flow, security, reverse,
    limit_ip, limit_hwid, total_gb, expiry_time, enable, tg_id, group_name,
    comment, reset, reset_day, reset_weekday, reset_max, traffic_reset,
    traffic_reset_day, created_at, updated_at, sync_orphaned_at
) VALUES (
    1, ?, ?, ?, ?, ?, '', 'auto', '',
    0, 0, 0, 0, 1, 0, '',
    '', 0, 0, 0, 0, 'never',
    1, ?, ?, 0
)
""", (email, sub_id, client_uuid, password, password, now_ms, now_ms))

def insert_inbound(inb_id, port, protocol, tag, remark, settings_str, stream_str):
    if has_exclude_from_sub:
        c.execute("""
        INSERT OR REPLACE INTO inbounds (
            id, user_id, up, down, total, remark, sub_sort_index, exclude_from_sub,
            enable, expiry_time, traffic_reset, traffic_reset_day, last_traffic_reset_time,
            listen, port, protocol, settings, stream_settings, tag, sniffing,
            node_id, share_addr_strategy, share_addr, disable_flow, origin_node_guid
        ) VALUES (
            ?, 1, 0, 0, 0, ?, ?, 0,
            1, 0, 'never', 1, 0,
            '', ?, ?, ?, ?, ?, '{"enabled":true,"destOverride":["http","tls","quic","fakedns"],"routeOnly":false}',
            NULL, 'node', '', 0, ''
        )
        """, (inb_id, remark, inb_id, port, protocol, settings_str, stream_str, tag))
    else:
        c.execute("""
        INSERT OR REPLACE INTO inbounds (
            id, user_id, up, down, total, remark, sub_sort_index,
            enable, expiry_time, traffic_reset, traffic_reset_day, last_traffic_reset_time,
            listen, port, protocol, settings, stream_settings, tag, sniffing,
            node_id, share_addr_strategy, share_addr, disable_flow, origin_node_guid
        ) VALUES (
            ?, 1, 0, 0, 0, ?, ?,
            1, 0, 'never', 1, 0,
            '', ?, ?, ?, ?, ?, '{"enabled":true,"destOverride":["http","tls","quic","fakedns"],"routeOnly":false}',
            NULL, 'node', '', 0, ''
        )
        """, (inb_id, remark, inb_id, port, protocol, settings_str, stream_str, tag))

# 3. Inbound 1: Port cf_port (443) VLESS-WS-TLS (for Cloudflare CDN & Clean IPs)
if domain and cert_path and key_path:
    vless_settings = json.dumps({{
        "clients": [{{
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
        }}],
        "decryption": "none"
    }}, indent=2)

    vless_stream = json.dumps({{
        "network": "ws",
        "security": "tls",
        "tlsSettings": {{
            "serverName": domain,
            "minVersion": "1.2",
            "maxVersion": "1.3",
            "cipherSuites": "",
            "rejectUnknownSni": False,
            "disableSystemRoot": False,
            "enableSessionResumption": False,
            "certificates": [{{
                "ocspStapling": 0,
                "oneTimeLoading": False,
                "usage": "encipherment",
                "buildChain": False,
                "certificateFile": cert_path,
                "keyFile": key_path
            }}],
            "alpn": ["http/1.1"]
        }},
        "wsSettings": {{
            "acceptProxyProtocol": False,
            "path": "/ws",
            "headers": {{}}
        }}
    }})
    insert_inbound(1, cf_port, 'vless', f'in-{{cf_port}}-vless', f'VPS-CF-VLESS-{{cf_port}}', vless_settings, vless_stream)

# 4. Inbound 2: Port hy2_port UDP Hysteria 2
hy2_settings = json.dumps({{
    "clients": [{{
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
    }}],
    "version": 2
}}, indent=2)

hy2_tls_certs = [{{
    "ocspStapling": 0,
    "oneTimeLoading": False,
    "usage": "encipherment",
    "buildChain": False,
    "certificateFile": cert_path,
    "keyFile": key_path
}}] if (cert_path and key_path) else []

hy2_stream = json.dumps({{
    "network": "hysteria",
    "hysteriaSettings": {{
        "version": 2,
        "udpIdleTimeout": 60,
        "masquerade": {{
            "type": "",
            "dir": "",
            "url": "",
            "rewriteHost": False,
            "insecure": False,
            "content": "",
            "headers": {{}},
            "statusCode": 0
        }}
    }},
    "security": "tls",
    "tlsSettings": {{
        "serverName": domain if domain else "localhost",
        "minVersion": "1.2",
        "maxVersion": "1.3",
        "cipherSuites": "",
        "rejectUnknownSni": False,
        "disableSystemRoot": False,
        "enableSessionResumption": False,
        "certificates": hy2_tls_certs,
        "alpn": ["h3"]
    }},
    "finalmask": {{
        "udp": [{{
            "type": "salamander",
            "settings": {{
                "password": obfs_pass
            }}
        }}],
        "quicParams": {{
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
        }}
    }}
}})
insert_inbound(2, hy2_port, 'hysteria', f'in-{{hy2_port}}-hy2', f'VPS-Direct-Hy2-{{hy2_port}}', hy2_settings, hy2_stream)

# 5. Inbound 3: Port reality_port TCP VLESS-Reality
reality_settings = json.dumps({{
    "clients": [{{
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
    }}],
    "decryption": "none",
    "encryption": "none"
}}, indent=2)

reality_stream = json.dumps({{
    "network": "tcp",
    "tcpSettings": {{
        "acceptProxyProtocol": False,
        "header": {{
            "type": "none"
        }}
    }},
    "security": "reality",
    "realitySettings": {{
        "show": False,
        "xver": 0,
        "target": f"{{reality_sni}}:443",
        "serverNames": [
            reality_sni,
            f"services.{{reality_sni}}",
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
        "settings": {{
            "publicKey": reality_pubkey,
            "fingerprint": "chrome",
            "serverName": "",
            "spiderX": ""
        }}
    }}
}})
insert_inbound(3, reality_port, 'vless', f'in-{{reality_port}}-reality', f'VPS-Direct-Reality-{{reality_port}}', reality_settings, reality_stream)

# 6. Associate client with inbounds
for inb_id in [1, 2, 3]:
    c.execute("""
    INSERT OR REPLACE INTO client_inbounds (client_id, inbound_id, flow_override, created_at)
    VALUES (1, ?, '', ?)
    """, (inb_id, now_ms))

conn.commit()
conn.close()
print("SUCCESS: 3X-UI DYNAMIC INBOUNDS CONFIGURED CLEANLY")
'''
    return script
