#!/usr/bin/env python3
"""
Client Node Builder:
Produces share links and matching Clash/Mihomo proxy entries from one source of
truth, so links, local YAML, QR codes and reports always describe the same nodes.
Each node carries explicit route metadata ('direct' or 'cdn').
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlencode

# Public Cloudflare anycast addresses; reachability differs per network, so these are
# starting points for the user's own testing, not guarantees.
CARRIER_CLEAN_IPS = {
    "unicom": [("162.159.193.1", "a"), ("104.16.160.1", "b")],
    "mobile": [("162.159.192.1", "a"), ("172.67.160.1", "b")],
    "telecom": [("104.17.160.1", "a"), ("162.159.195.1", "b")],
    "overseas": [("104.16.160.1", "a"), ("104.17.160.1", "b")],
}


def _host(server: str) -> str:
    return f"[{server}]" if ":" in server else server


def _node(name: str, route: str, uri: str, clash: Dict[str, Any], qr: bool) -> Dict[str, Any]:
    return {"name": name, "route": route, "uri": uri, "clash": dict(clash, name=name), "qr": qr}


def reality_node(prefix: str, uuid: str, server: str, port: int, sni: str, public_key: str,
                 short_id: str) -> Dict[str, Any]:
    name = f"{prefix}-reality"
    params = urlencode({"encryption": "none", "flow": "xtls-rprx-vision", "security": "reality", "sni": sni,
                        "fp": "chrome", "pbk": public_key, "sid": short_id, "type": "tcp"})
    return _node(name, "direct", f"vless://{uuid}@{_host(server)}:{port}?{params}#{quote(name)}", {
        "type": "vless", "server": server, "port": port, "uuid": uuid, "network": "tcp", "tls": True,
        "udp": True, "flow": "xtls-rprx-vision", "servername": sni,
        "reality-opts": {"public-key": public_key, "short-id": short_id}, "client-fingerprint": "chrome",
    }, qr=True)


def hy2_node(prefix: str, password: str, server: str, port: int, sni: Optional[str] = None,
             pin_sha256: Optional[str] = None, obfs_password: Optional[str] = None) -> Dict[str, Any]:
    """`pin_sha256` (colon-separated hex) pins a self-signed certificate for bare-IP deployments."""
    name = f"{prefix}-hy2"
    params: Dict[str, str] = {}
    clash: Dict[str, Any] = {"type": "hysteria2", "server": server, "port": port, "password": password,
                             "alpn": ["h3"], "skip-cert-verify": False}
    if sni:
        params["sni"] = sni
        clash["sni"] = sni
    if pin_sha256:
        params["insecure"] = "1"
        params["pinSHA256"] = pin_sha256
        clash["fingerprint"] = pin_sha256.replace(":", "").lower()
    if obfs_password:
        params["obfs"] = "salamander"
        params["obfs-password"] = obfs_password
        clash["obfs"] = "salamander"
        clash["obfs-password"] = obfs_password
    query = f"?{urlencode(params)}" if params else ""
    uri = f"hysteria2://{quote(password, safe='')}@{_host(server)}:{port}/{query}#{quote(name)}"
    return _node(name, "direct", uri, clash, qr=True)


def ws_node(name: str, uuid: str, server: str, host: str, ws_path: str, qr: bool = False) -> Dict[str, Any]:
    params = urlencode({"encryption": "none", "type": "ws", "security": "tls", "path": ws_path, "host": host,
                        "sni": host})
    return _node(name, "cdn", f"vless://{uuid}@{_host(server)}:443?{params}#{quote(name)}", {
        "type": "vless", "server": server, "port": 443, "uuid": uuid, "network": "ws", "tls": True,
        "udp": True, "servername": host, "ws-opts": {"path": ws_path, "headers": {"Host": host}},
    }, qr=qr)


def cdn_nodes(prefix: str, uuid: str, domain: str, ws_path: str,
              clean_ips: Sequence[Tuple[str, str]], ipv6_domain: Optional[str] = None) -> List[Dict[str, Any]]:
    nodes = [ws_node(f"{prefix}-cdn", uuid, domain, domain, ws_path, qr=True)]
    for clean_ip, label in clean_ips:
        nodes.append(ws_node(f"{prefix}-cdn-{label}", uuid, clean_ip, domain, ws_path))
    if ipv6_domain:
        nodes.append(ws_node(f"{prefix}-cdn-v6", uuid, ipv6_domain, ipv6_domain, ws_path))
    return nodes
