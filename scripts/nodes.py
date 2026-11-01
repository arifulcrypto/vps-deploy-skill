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

# Measured through real Cloudflare: these ranges answer on 443 but time out on 2053, 2083 and 8443.
HTTPS_443_ONLY_PREFIXES = ("162.159.",)


def clean_ips_for(isp: str, port: int) -> List[Tuple[str, str]]:
    """Clean IPs for a carrier that can serve this port, topped up from the general list when needed."""
    ips = list(CARRIER_CLEAN_IPS[isp])
    if port == 443:
        return ips
    usable = [ip for ip, _ in ips if not ip.startswith(HTTPS_443_ONLY_PREFIXES)]
    spares = [ip for ip, _ in CARRIER_CLEAN_IPS["overseas"] if ip not in usable]
    return list(zip((usable + spares)[:len(ips)], "abcdef"))


def _host(server: str) -> str:
    return f"[{server}]" if ":" in server else server


def _node(name: str, route: str, uri: str, clash: Dict[str, Any], qr: bool) -> Dict[str, Any]:
    return {"name": name, "route": route, "uri": uri, "clash": dict(clash, name=name), "qr": qr}


def reality_node(prefix: str, uuid: str, server: str, port: int, sni: str, public_key: str,
                 short_id: str, name: Optional[str] = None, route: str = "direct") -> Dict[str, Any]:
    name = name or f"{prefix}-reality"
    params = urlencode({"encryption": "none", "flow": "xtls-rprx-vision", "security": "reality", "sni": sni,
                        "fp": "chrome", "pbk": public_key, "sid": short_id, "type": "tcp"})
    return _node(name, route, f"vless://{uuid}@{_host(server)}:{port}?{params}#{quote(name)}", {
        "type": "vless", "server": server, "port": port, "uuid": uuid, "network": "tcp", "tls": True,
        "udp": True, "flow": "xtls-rprx-vision", "servername": sni,
        "reality-opts": {"public-key": public_key, "short-id": short_id, "support-x25519mlkem768": True},
        "client-fingerprint": "chrome",
    }, qr=True)


def vision_tls_node(prefix: str, uuid: str, domain: str, port: int) -> Dict[str, Any]:
    """VLESS + TLS + Vision with a publicly trusted certificate, for clients without REALITY."""
    name = f"{prefix}-vision"
    params = urlencode({"encryption": "none", "flow": "xtls-rprx-vision", "security": "tls", "sni": domain,
                        "fp": "chrome", "alpn": "http/1.1", "type": "tcp"})
    return _node(name, "direct", f"vless://{uuid}@{_host(domain)}:{port}?{params}#{quote(name)}", {
        "type": "vless", "server": domain, "port": port, "uuid": uuid, "network": "tcp", "tls": True, "udp": True,
        "flow": "xtls-rprx-vision", "servername": domain, "alpn": ["http/1.1"], "client-fingerprint": "chrome",
    }, qr=True)


def hy2_node(prefix: str, password: str, server: str, port: int, sni: Optional[str] = None,
             pin_sha256: Optional[str] = None, obfs_password: Optional[str] = None,
             up_mbps: Optional[int] = None, down_mbps: Optional[int] = None) -> Dict[str, Any]:
    """
    `pin_sha256` (colon-separated hex) pins a self-signed certificate for bare-IP deployments.
    `up_mbps`/`down_mbps` are only set when known: a client-declared rate selects Brutal, which
    sends at that rate regardless of loss, so a wrong guess hurts more than leaving BBR in charge.
    """
    name = f"{prefix}-hy2"
    params: Dict[str, str] = {}
    clash: Dict[str, Any] = {"type": "hysteria2", "server": server, "port": port, "password": password,
                             "alpn": ["h3"], "skip-cert-verify": False}
    if up_mbps and down_mbps:
        clash["up"] = f"{up_mbps} Mbps"
        clash["down"] = f"{down_mbps} Mbps"
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


def ws_node(name: str, uuid: str, server: str, host: str, ws_path: str, qr: bool = False,
            port: int = 443) -> Dict[str, Any]:
    params = urlencode({"encryption": "none", "type": "ws", "security": "tls", "path": ws_path, "host": host,
                        "sni": host})
    return _node(name, "cdn", f"vless://{uuid}@{_host(server)}:{port}?{params}#{quote(name)}", {
        "type": "vless", "server": server, "port": port, "uuid": uuid, "network": "ws", "tls": True,
        "udp": True, "servername": host, "ws-opts": {"path": ws_path, "headers": {"Host": host}},
    }, qr=qr)


def xhttp_node(name: str, uuid: str, server: str, host: str, path: str, port: int = 443,
               qr: bool = False) -> Dict[str, Any]:
    """VLESS over XHTTP. packet-up needs nothing from the CDN beyond ordinary HTTP requests."""
    params = urlencode({"encryption": "none", "type": "xhttp", "security": "tls", "path": path, "host": host,
                        "sni": host, "mode": "packet-up", "fp": "chrome"})
    return _node(name, "cdn", f"vless://{uuid}@{_host(server)}:{port}?{params}#{quote(name)}", {
        "type": "vless", "server": server, "port": port, "uuid": uuid, "network": "xhttp", "tls": True,
        "udp": True, "servername": host, "client-fingerprint": "chrome",
        "xhttp-opts": {"path": path, "host": host, "mode": "packet-up"},
    }, qr=qr)


def xhttp_nodes(prefix: str, uuid: str, domain: str, path: str, clean_ips: Sequence[Tuple[str, str]],
                port: int = 443) -> List[Dict[str, Any]]:
    nodes = [xhttp_node(f"{prefix}-xhttp", uuid, domain, domain, path, port, qr=True)]
    for clean_ip, label in clean_ips:
        nodes.append(xhttp_node(f"{prefix}-xhttp-{label}", uuid, clean_ip, domain, path, port))
    return nodes


def cdn_nodes(prefix: str, uuid: str, domain: str, ws_path: str,
              clean_ips: Sequence[Tuple[str, str]], ipv6_domain: Optional[str] = None,
              port: int = 443) -> List[Dict[str, Any]]:
    nodes = [ws_node(f"{prefix}-cdn", uuid, domain, domain, ws_path, qr=True, port=port)]
    for clean_ip, label in clean_ips:
        nodes.append(ws_node(f"{prefix}-cdn-{label}", uuid, clean_ip, domain, ws_path, port=port))
    if ipv6_domain:
        nodes.append(ws_node(f"{prefix}-cdn-v6", uuid, ipv6_domain, ipv6_domain, ws_path, port=port))
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
    params = {"security": "tls", "type": network}
    if sni:
        params["sni"] = sni
    query = f"?{urlencode(params)}"
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
