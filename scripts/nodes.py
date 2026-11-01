#!/usr/bin/env python3
"""
Client Node Builder:
Produces share links and matching Clash/Mihomo proxy entries from one source of
truth, so links, local YAML, QR codes and reports always describe the same nodes.
Each node carries explicit route metadata:
  - 'direct': High performance direct connection to VPS datacenter IP
  - 'cdn': Cloudflare CDN proxy with carrier clean IPs
  - 'relay': Layer 4 port forward / NAT relay to residential / home broadband exit
  - 'residential': Commercial residential / sticky session proxy (metered traffic)
"""
import base64
import json
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
        "reality-opts": {"public-key": public_key, "short-id": short_id, "support-x25519mlkem768": True},
        "client-fingerprint": "chrome",
    }, qr=True)


def hy2_node(prefix: str, password: str, server: str, port: int, sni: Optional[str] = None,
             pin_sha256: Optional[str] = None, obfs_password: Optional[str] = None) -> Dict[str, Any]:
    """`pin_sha256` (colon-separated hex) pins a self-signed certificate for bare-IP deployments."""
    name = f"{prefix}-hy2"
    params: Dict[str, str] = {}
    clash: Dict[str, Any] = {"type": "hysteria2", "server": server, "port": port, "password": password,
                             "alpn": ["h3"], "skip-cert-verify": False, "up": "300 Mbps", "down": "1000 Mbps"}
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


def vmess_ws_node(name: str, uuid: str, server: str, port: int, ws_path: str,
                  host: Optional[str] = None, tls: bool = False, qr: bool = False) -> Dict[str, Any]:
    """233boy-compatible VMess+WS protocol for maximum legacy client compatibility."""
    vj = {
        "v": "2",
        "ps": name,
        "add": server,
        "port": str(port),
        "id": uuid,
        "aid": "0",
        "scy": "auto",
        "net": "ws",
        "type": "none",
        "host": host or "",
        "path": ws_path,
        "tls": "tls" if tls else "",
        "sni": host or "",
    }
    raw = json.dumps(vj, separators=(",", ":")).encode("utf-8")
    uri = f"vmess://{base64.b64encode(raw).decode('utf-8')}"
    clash: Dict[str, Any] = {
        "type": "vmess",
        "server": server,
        "port": port,
        "uuid": uuid,
        "alterId": 0,
        "cipher": "auto",
        "network": "ws",
        "ws-opts": {"path": ws_path},
    }
    if host:
        clash["ws-opts"]["headers"] = {"Host": host}
    if tls:
        clash["tls"] = True
        if host:
            clash["servername"] = host
    return _node(name, "direct", uri, clash, qr=qr)


def trojan_node(name: str, password: str, server: str, port: int, sni: Optional[str] = None,
                network: str = "tcp", qr: bool = False) -> Dict[str, Any]:
    """Trojan-GFW compatible standard HTTPS disguised node."""
    params = {"sni": sni} if sni else {}
    query = f"?{urlencode(params)}" if params else ""
    uri = f"trojan://{quote(password, safe='')}@{_host(server)}:{port}{query}#{quote(name)}"
    clash: Dict[str, Any] = {
        "type": "trojan",
        "server": server,
        "port": port,
        "password": password,
        "network": network,
    }
    if sni:
        clash["sni"] = sni
    return _node(name, "direct", uri, clash, qr=qr)


def relay_reality_node(name: str, relay_server: str, relay_port: int,
                       original_node: Dict[str, Any]) -> Dict[str, Any]:
    """
    Builds a 4-layer Realm passthrough relay node.
    Preserves original UUID, pbk, sni, sid, and flow, while directing client traffic to relay_server:relay_port.
    Carries route='relay' to guarantee isolation from automated url-test groups.
    """
    orig_clash = original_node.get("clash", original_node)
    clash = dict(orig_clash)
    clash["name"] = name
    clash["server"] = relay_server
    clash["port"] = relay_port

    orig_uri = original_node.get("uri", "")
    uuid = orig_clash.get("uuid", "")
    if "?" in orig_uri:
        query = orig_uri.split("?", 1)[1].split("#", 1)[0]
    else:
        reality_opts = orig_clash.get("reality-opts", {})
        params = {
            "encryption": "none",
            "flow": orig_clash.get("flow", "xtls-rprx-vision"),
            "security": "reality",
            "sni": orig_clash.get("servername", ""),
            "fp": orig_clash.get("client-fingerprint", "chrome"),
            "pbk": reality_opts.get("public-key", ""),
            "sid": reality_opts.get("short-id", ""),
            "type": "tcp",
        }
        query = urlencode(params)

    uri = f"vless://{uuid}@{_host(relay_server)}:{relay_port}?{query}#{quote(name)}"
    return _node(name, "relay", uri, clash, qr=False)


def residential_socks5_node(name: str, server: str, port: int, username: str, password: str,
                            udp: bool = True) -> Dict[str, Any]:
    """
    Builds a commercial residential / sticky session proxy node (IPRoyal, IPCook, DataImpulse).
    route='residential' ensures strict exclusion from url-test latency tests to protect metered bandwidth.
    """
    user_enc = quote(username, safe="")
    pass_enc = quote(password, safe="")
    uri = f"socks5://{user_enc}:{pass_enc}@{_host(server)}:{port}#{quote(name)}"
    clash = {
        "type": "socks5",
        "server": server,
        "port": port,
        "username": username,
        "password": password,
        "udp": udp,
    }
    return _node(name, "residential", uri, clash, qr=False)
