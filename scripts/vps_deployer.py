#!/usr/bin/env python3
"""
VPS Deployer Unified Automation Engine:
Connects to a VPS, installs/configures 3X-UI and produces client artifacts.

Profiles
  unified       Default. VLESS-REALITY (on 443 when no domain needs it, otherwise a random
                high port), Hysteria 2 on a random high UDP port, and VLESS-WS-TLS on 443
                for a Cloudflare-proxied domain. `legacy` is an alias.
  vision-tls    One public HTTPS port: VLESS + TLS + Vision with a real certificate, for
                clients without REALITY. Other connections fall back to the local website.
  reality-self  One public HTTPS port: VLESS-REALITY-Vision whose target is the operator's
                own loopback HTTPS website (Nginx). Requires a DNS-only domain. An optional
                `cdn_domain` adds a Cloudflare WebSocket path on the same port.

No report, links or QR codes are written unless all remote steps and listener checks pass.
The panel login probe only warns unless --fail-closed is set. Re-runs reuse the identity,
ports and keys of the last verified deployment in /etc/vps-skill/state.json. A failed
activation restores the previous panel database.
"""
import argparse
import datetime
import ipaddress
import json
import os
import re
import secrets
import sys
import uuid
from typing import Any, Dict, List, Optional, Tuple

# Allow `python3 scripts/vps_deployer.py` as well as `python3 -m scripts.vps_deployer`
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts import boot_check, cloudflare_dns, provision, web_profile  # noqa: E402
from scripts.clash_generator import generate_local_clash_yaml  # noqa: E402
from scripts.db_configurator import (REMOTE_DB_SCRIPT, build_db_payload, exit_outbound, hy2_inbound,  # noqa: E402
                                     reality_inbound, trojan_inbound, vision_tls_inbound, vmess_ws_inbound,
                                     ws_inbound, ws_local_inbound, xhttp_local_inbound, xhttp_tls_inbound)
from scripts.nodes import (CARRIER_CLEAN_IPS, cdn_nodes, clean_ips_for, hy2_node, reality_node,  # noqa: E402
                           relay_reality_node, residential_socks5_node, trojan_node, vision_tls_node,
                           vmess_ws_node, xhttp_nodes)
from scripts.panel_probe import REMOTE_PROBE_SCRIPT  # noqa: E402
from scripts.port_utils import (CLOUDFLARE_HTTPS_PORTS, generate_unambiguous_password,  # noqa: E402
                                normalize_base_path, random_path, random_port)
from scripts.qr_engine import generate_qr  # noqa: E402
from scripts.remote import DeploymentError, SSHTarget, last_json_line, parse_kv  # noqa: E402
from scripts.report import render_report, secure_dir, write_secret, write_secret_json  # noqa: E402
from scripts.sub_converter import build_subscription_urls  # noqa: E402

PROFILES = ("unified", "legacy", "reality-self", "vision-tls")
WEBSITE_PROFILES = ("reality-self", "vision-tls")
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
USER_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
PATH_RE = re.compile(r"^/?[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/?$")
VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+$")
EMAIL_RE = re.compile(r"^[^@\s'\"]+@[a-z0-9.-]+\.[a-z]{2,}$")
PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
DEFAULT_REALITY_SNI = "addons.mozilla.org"
DEFAULT_BACKEND_PORT = 8443
DEFAULT_SUB_PORT = 2096
CERT_ROOT = "/root/cert"
CERT_MODES = ("http-01", "dns-01")
EXTRA_PROTOCOLS = ("vmess", "trojan")
CDN_TRANSPORTS = ("ws", "xhttp", "both")
EXIT_PROTOCOLS = ("socks", "http")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")

__all__ = ["DeploymentError", "validate_config", "normalize_config", "build_plan", "deploy_vps", "main"]


# ---------------------------------------------------------------------------
# Validation & normalization
# ---------------------------------------------------------------------------

def _port(value: Any, name: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise DeploymentError(f"Invalid {name}: '{value}'. Must be an integer between 1 and 65535.")
    if not 1 <= port <= 65535:
        raise DeploymentError(f"Invalid {name}: '{value}'. Must be an integer between 1 and 65535.")
    return port


def _str(cfg: Dict[str, Any], key: str) -> str:
    return str(cfg.get(key) or "").strip()


def validate_config(cfg: Dict[str, Any]) -> None:
    """Reject anything that could break remote commands or produce an unusable deployment."""
    ip = _str(cfg, "ip")
    if not ip:
        raise DeploymentError("Missing required parameter: 'ip' (Target server IPv4 address)")
    try:
        ipaddress.IPv4Address(ip)
    except ValueError:
        raise DeploymentError(f"Invalid IPv4 address format: '{ip}'")

    if not cfg.get("ssh_pass") and not cfg.get("ssh_key"):
        raise DeploymentError("Missing authentication credentials: 'ssh_pass' (root password) or 'ssh_key' is required")
    _port(cfg.get("ssh_port") or 22, "SSH port")

    ipv6 = _str(cfg, "ipv6")
    if ipv6:
        try:
            ipaddress.IPv6Address(ipv6)
        except ValueError:
            raise DeploymentError(f"Invalid IPv6 address format: '{ipv6}'")

    for key in ("domain", "ipv6_domain", "panel_domain", "reality_sni", "cdn_domain"):
        value = _str(cfg, key).lower()
        if value and not DOMAIN_RE.match(value):
            raise DeploymentError(f"Invalid {key}: '{value}' is not a valid DNS hostname.")

    profile = _str(cfg, "profile") or "unified"
    if profile not in PROFILES:
        raise DeploymentError(f"Invalid profile '{profile}'. Choose one of: {', '.join(PROFILES)}")
    if profile in WEBSITE_PROFILES and not _str(cfg, "domain"):
        raise DeploymentError(f"Profile '{profile}' requires 'domain' (a DNS-only / grey-cloud A record to this VPS).")
    cdn_domain = _str(cfg, "cdn_domain").lower()
    if cdn_domain and profile != "reality-self":
        raise DeploymentError("'cdn_domain' needs profile 'reality-self'. Other profiles use 'domain' for the CDN.")
    if cdn_domain and cdn_domain == _str(cfg, "domain").lower():
        raise DeploymentError("'cdn_domain' must differ from 'domain': REALITY owns that SNI.")

    cert_mode = _str(cfg, "cert_mode") or "http-01"
    if cert_mode not in CERT_MODES:
        raise DeploymentError(f"Invalid cert_mode '{cert_mode}'. Choose one of: {', '.join(CERT_MODES)}")
    needs_cert = any(_str(cfg, key) for key in ("domain", "panel_domain"))
    if cert_mode == "dns-01" and needs_cert and not cfg.get("cf_token"):
        raise DeploymentError("cert_mode 'dns-01' needs a Cloudflare API token: set 'cf_token' or CF_TOKEN.")
    if cfg.get("cf_token") and not TOKEN_RE.match(str(cfg["cf_token"])):
        raise DeploymentError("Invalid cf_token.")

    transport = _str(cfg, "cdn_transport")
    if transport and transport not in CDN_TRANSPORTS:
        raise DeploymentError(f"Invalid cdn_transport '{transport}'. Choose one of: {', '.join(CDN_TRANSPORTS)}")
    if transport == "both" and profile != "reality-self":
        raise DeploymentError("cdn_transport 'both' needs profile 'reality-self': Nginx shares one port between them.")
    if cfg.get("manage_dns") and not cfg.get("cf_token"):
        raise DeploymentError("manage_dns needs a Cloudflare API token: set 'cf_token' or CF_TOKEN.")
    exit_proxy = cfg.get("exit_proxy")
    if exit_proxy:
        if not isinstance(exit_proxy, dict) or not exit_proxy.get("server") or not exit_proxy.get("port"):
            raise DeploymentError("Invalid exit_proxy: 'server' and 'port' are required.")
        _port(exit_proxy["port"], "exit_proxy port")
        if exit_proxy.get("protocol", "socks") not in EXIT_PROTOCOLS:
            raise DeploymentError(f"Invalid exit_proxy protocol. Choose one of: {', '.join(EXIT_PROTOCOLS)}")
        if bool(exit_proxy.get("username")) != bool(exit_proxy.get("password")):
            raise DeploymentError("exit_proxy needs both username and password, or neither.")
    if _flag(cfg, "exit_all", False) and not exit_proxy:
        raise DeploymentError("exit_all needs exit_proxy.")
    if _flag(cfg, "hy2_masquerade", False):
        if profile != "reality-self":
            raise DeploymentError("hy2_masquerade needs profile 'reality-self', which provides the website.")
        if _flag(cfg, "hy2_obfs", True):
            raise DeploymentError("hy2_masquerade needs hy2_obfs off: Salamander hides the HTTP/3 endpoint.")

    extras = _extras(cfg)
    unknown = sorted(set(extras) - set(EXTRA_PROTOCOLS))
    if unknown:
        raise DeploymentError(f"Unknown extra_protocols: {', '.join(unknown)}. Choose from: {', '.join(EXTRA_PROTOCOLS)}")
    if "trojan" in extras and not _str(cfg, "domain"):
        raise DeploymentError("extra protocol 'trojan' needs 'domain' for its certificate.")
    _validate_outbound_nodes(cfg)
    for key in ("hy2_up", "hy2_down"):
        if cfg.get(key) not in (None, "") and int(cfg[key]) < 1:
            raise DeploymentError(f"Invalid {key}: expected Mbps as a positive integer.")
    if bool(cfg.get("hy2_up")) != bool(cfg.get("hy2_down")):
        raise DeploymentError("Set both hy2_up and hy2_down, or neither.")

    isp = (_str(cfg, "client_isp") or "unicom").lower()
    if isp not in CARRIER_CLEAN_IPS:
        raise DeploymentError(f"Invalid client_isp '{isp}'. Choose one of: {', '.join(CARRIER_CLEAN_IPS)}")
    if (_str(cfg, "lang") or "en").lower() not in ("en", "zh"):
        raise DeploymentError("Invalid lang. Choose 'en' or 'zh'.")

    tcp_ports = {}
    for key in ("panel_port", "reality_port", "web_backend_port", "sub_port", "vmess_port", "trojan_port", "exit_port"):
        if cfg.get(key) not in (None, ""):
            tcp_ports[key] = _port(cfg[key], key)
    if cfg.get("hy2_port") not in (None, ""):
        _port(cfg["hy2_port"], "hy2_port")
    https_port = _port(cfg.get("https_port") or 443, "https_port")
    reserved = {80: "HTTP/ACME", int(cfg.get("ssh_port") or 22): "SSH"}
    if _str(cfg, "domain"):
        reserved[https_port] = "HTTPS"
    seen: Dict[int, str] = {}
    for key, port in tcp_ports.items():
        if port in reserved:
            raise DeploymentError(f"{key}={port} collides with the {reserved[port]} port.")
        if port in seen:
            raise DeploymentError(f"{key}={port} collides with {seen[port]}.")
        seen[port] = key

    for key in ("panel_pass", "node_pass", "obfs_password"):
        if cfg.get(key) and not SECRET_RE.match(str(cfg[key])):
            raise DeploymentError(f"Invalid {key}: use 8-64 characters from [A-Za-z0-9_-].")
    if cfg.get("panel_user") and not USER_RE.match(str(cfg["panel_user"])):
        raise DeploymentError("Invalid panel_user: use 3-32 characters from [A-Za-z0-9_.-].")
    if cfg.get("panel_base_path") and not PATH_RE.match(str(cfg["panel_base_path"])):
        raise DeploymentError("Invalid panel_base_path: use path segments of [A-Za-z0-9_-].")
    if cfg.get("xui_version") and not VERSION_RE.match(str(cfg["xui_version"])):
        raise DeploymentError("Invalid xui_version: expected a release tag such as 'v3.11.0'.")
    if cfg.get("acme_email") and not EMAIL_RE.match(str(cfg["acme_email"]).lower()):
        raise DeploymentError("Invalid acme_email.")
    if cfg.get("node_prefix") and not PREFIX_RE.match(str(cfg["node_prefix"])):
        raise DeploymentError("Invalid node_prefix: use 1-24 characters from [A-Za-z0-9_-].")
    title = str(cfg.get("site_title") or "")
    if len(title) > 80 or any(ord(ch) < 32 for ch in title):
        raise DeploymentError("Invalid site_title: at most 80 printable characters.")


def _extras(cfg: Dict[str, Any]) -> List[str]:
    value = cfg.get("extra_protocols") or []
    if isinstance(value, str):
        value = value.split(",")
    return sorted({str(item).strip().lower() for item in value if str(item).strip()})


def _validate_outbound_nodes(cfg: Dict[str, Any]) -> None:
    """Client-side relay and residential entries: these add nodes, not server configuration."""
    for key, fields in (("relays", ("name", "server", "port")),
                        ("residential", ("name", "server", "port", "username", "password"))):
        items = cfg.get(key) or []
        if not isinstance(items, list):
            raise DeploymentError(f"Invalid {key}: expected a list.")
        for item in items:
            missing = [f for f in fields if not isinstance(item, dict) or not item.get(f)]
            if missing:
                raise DeploymentError(f"Invalid {key} entry: missing {', '.join(missing)}.")
            _port(item["port"], f"{key} port")
            if not PREFIX_RE.match(str(item["name"])):
                raise DeploymentError(f"Invalid {key} name '{item['name']}': use 1-24 characters from [A-Za-z0-9_-].")


def _flag(cfg: Dict[str, Any], key: str, default: bool) -> bool:
    value = cfg.get(key)
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def normalize_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    validate_config(cfg)
    profile = _str(cfg, "profile") or "unified"
    domain = _str(cfg, "domain").lower() or None
    c = {
        "ip": _str(cfg, "ip"),
        "ssh_port": int(cfg.get("ssh_port") or 22),
        "ssh_user": _str(cfg, "ssh_user") or "root",
        "ssh_pass": cfg.get("ssh_pass") or None,
        "ssh_key": os.path.expanduser(cfg["ssh_key"]) if cfg.get("ssh_key") else None,
        "ssh_known_hosts": os.path.expanduser(cfg["ssh_known_hosts"]) if cfg.get("ssh_known_hosts") else None,
        "profile": profile,
        "domain": domain,
        "cdn_domain": _str(cfg, "cdn_domain").lower() or None,
        "cdn_transport": _str(cfg, "cdn_transport") or ("both" if profile == "reality-self" else "ws"),
        "manage_dns": _flag(cfg, "manage_dns", False),
        "exit_proxy": cfg.get("exit_proxy") or None,
        "exit_port": int(cfg["exit_port"]) if cfg.get("exit_port") else None,
        "exit_all": _flag(cfg, "exit_all", False),
        "hy2_masquerade": _flag(cfg, "hy2_masquerade", False),
        "https_port": int(cfg.get("https_port") or 443),
        "cert_mode": _str(cfg, "cert_mode") or "http-01",
        "cf_token": cfg.get("cf_token") or None,
        "extra_protocols": _extras(cfg),
        "relays": cfg.get("relays") or [],
        "residential": cfg.get("residential") or [],
        "hy2_up": int(cfg["hy2_up"]) if cfg.get("hy2_up") else None,
        "hy2_down": int(cfg["hy2_down"]) if cfg.get("hy2_down") else None,
        "ipv6": _str(cfg, "ipv6") or None,
        "ipv6_domain": (_str(cfg, "ipv6_domain").lower() or None) if profile not in WEBSITE_PROFILES else None,
        "panel_domain": _str(cfg, "panel_domain").lower() or None,
        "reality_sni": _str(cfg, "reality_sni").lower() or DEFAULT_REALITY_SNI,
        "client_isp": (_str(cfg, "client_isp") or "unicom").lower(),
        "client_ip": _str(cfg, "client_ip") or "n/a",
        "client_location": _str(cfg, "client_location") or "n/a",
        "lang": (_str(cfg, "lang") or "en").lower(),
        "output_dir": os.path.abspath(_str(cfg, "output_dir") or f"./output/{_str(cfg, 'ip')}"),
        "panel_port": int(cfg["panel_port"]) if cfg.get("panel_port") else None,
        "hy2_port": int(cfg["hy2_port"]) if cfg.get("hy2_port") else None,
        "reality_port": int(cfg["reality_port"]) if cfg.get("reality_port") else None,
        "sub_port": int(cfg.get("sub_port") or DEFAULT_SUB_PORT),
        "enable_sub": _flag(cfg, "enable_sub", True),
        "vmess_port": int(cfg["vmess_port"]) if cfg.get("vmess_port") else None,
        "trojan_port": int(cfg["trojan_port"]) if cfg.get("trojan_port") else None,
        "web_backend_port": int(cfg.get("web_backend_port") or DEFAULT_BACKEND_PORT),
        "panel_user": cfg.get("panel_user") or None,
        "panel_pass": cfg.get("panel_pass") or None,
        "panel_base_path": normalize_base_path(cfg["panel_base_path"]) if cfg.get("panel_base_path") else None,
        "panel_private": _flag(cfg, "panel_private", False),
        "node_pass": cfg.get("node_pass") or None,
        "obfs_password": cfg.get("obfs_password") or None,
        "enable_hy2": _flag(cfg, "enable_hy2", profile not in WEBSITE_PROFILES),
        "hy2_obfs": _flag(cfg, "hy2_obfs", True),
        "node_prefix": cfg.get("node_prefix") or "srv",
        "site_title": cfg.get("site_title") or (domain.split(".")[-2].capitalize() if domain else "Welcome"),
        "site_description": cfg.get("site_description") or "Notes, drafts and small projects.",
        "acme_email": (cfg.get("acme_email") or "").lower() or None,
        "xui_version": cfg.get("xui_version") or None,
        "reinstall_xui": _flag(cfg, "reinstall_xui", False),
        "adopt_existing_panel": _flag(cfg, "adopt_existing_panel", True),
        "stop_conflicting_services": _flag(cfg, "stop_conflicting_services", True),
        "rotate_secrets": _flag(cfg, "rotate_secrets", False),
        "online_sub": _flag(cfg, "online_sub", True),
        "fail_closed": _flag(cfg, "fail_closed", False),
    }
    return c


# ---------------------------------------------------------------------------
# Planning (pure: no network access)
# ---------------------------------------------------------------------------

def cert_domains(c: Dict[str, Any]) -> List[str]:
    domains = [c["domain"], c["cdn_domain"], c["ipv6_domain"], c["panel_domain"]]
    return list(dict.fromkeys(d for d in domains if d))


def build_plan(c: Dict[str, Any], state: Optional[Dict[str, Any]] = None,
               listeners: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Derive ports and secrets. Values stored in `state` are reused (stable client links and
    firewall rules across re-runs) unless rotation is requested or an explicit override is set.
    """
    prev = dict(state or {})
    listeners = listeners or []
    rotate = c["rotate_secrets"]

    def keep(key: str, generate):
        return prev[key] if prev.get(key) and not rotate else generate()

    s: Dict[str, Any] = {"version": 1, "profile": c["profile"]}
    s["deploy_id"] = prev.get("deploy_id") or secrets.token_hex(4)
    s["email"] = f"vps-skill-{s['deploy_id']}"
    s["client_uuid"] = keep("client_uuid", lambda: str(uuid.uuid4()))
    s["sub_id"] = keep("sub_id", lambda: secrets.token_hex(8))
    s["node_pass"] = c["node_pass"] or keep("node_pass", lambda: generate_unambiguous_password(20))
    s["obfs_password"] = c["obfs_password"] or keep("obfs_password", lambda: secrets.token_hex(12))
    s["reality_short_id"] = keep("reality_short_id", lambda: secrets.token_hex(4))
    s["panel_user"] = c["panel_user"] or keep("panel_user", lambda: "u" + generate_unambiguous_password(7))
    s["panel_pass"] = c["panel_pass"] or keep("panel_pass", lambda: generate_unambiguous_password(20))
    s["panel_base_path"] = c["panel_base_path"] or prev.get("panel_base_path") or random_path()
    s["ws_path"] = prev.get("ws_path") or random_path(9).rstrip("/")
    s["vmess_path"] = prev.get("vmess_path") or random_path(9).rstrip("/")
    s["xhttp_path"] = prev.get("xhttp_path") or random_path(9).rstrip("/")
    if not rotate:
        s["reality_private_key"] = prev.get("reality_private_key", "")
        s["reality_public_key"] = prev.get("reality_public_key", "")

    # Without a domain nothing else needs the HTTPS port, so REALITY may take it.
    https_port = c["https_port"]
    reserved_tcp = {80, c["ssh_port"], c["web_backend_port"]}
    if c["domain"]:
        reserved_tcp.add(https_port)

    def tcp_busy(port: int) -> bool:
        return bool(provision.port_users(listeners, "tcp", port))

    def udp_busy(port: int) -> bool:
        return bool(provision.port_users(listeners, "udp", port))

    def choose(kind: str, proto: str, avoid: set) -> int:
        explicit = c.get(f"{kind}_port")
        if explicit:
            foreign = provision.foreign_users(listeners, proto, explicit)
            if foreign:
                raise DeploymentError(f"{kind}_port {explicit}/{proto} is already used by: {', '.join(foreign)}")
            return explicit
        previous = prev.get(f"{kind}_port")
        if kind == "panel" and c.get("panel_domain"):
            if previous in CLOUDFLARE_HTTPS_PORTS and not provision.foreign_users(listeners, proto, previous):
                return previous
            for cf_port in CLOUDFLARE_HTTPS_PORTS:
                if cf_port not in avoid and not (tcp_busy(cf_port) if proto == "tcp" else udp_busy(cf_port)):
                    return cf_port
        if previous and previous not in avoid and not provision.foreign_users(listeners, proto, previous):
            return previous
        if kind == "reality" and not c["domain"] and https_port not in avoid and not tcp_busy(https_port):
            return https_port
        return random_port(kind, avoid, tcp_busy if proto == "tcp" else udp_busy)

    s["panel_port"] = choose("panel", "tcp", reserved_tcp)
    taken = reserved_tcp | {s["panel_port"]}
    if c["profile"] in WEBSITE_PROFILES:
        s["reality_port"] = https_port
    else:
        s["reality_port"] = choose("reality", "tcp", taken)
    taken |= {s["reality_port"]}
    s["hy2_port"] = choose("hy2", "udp", set()) if c["enable_hy2"] else None
    for kind in c["extra_protocols"] + (["exit"] if c["exit_proxy"] and not c["exit_all"] else []):
        s[f"{kind}_port"] = choose(kind, "tcp", taken)
        taken |= {s[f"{kind}_port"]}
    s["sub_port"] = c["sub_port"] if c["enable_sub"] else None
    if c["cdn_domain"]:
        if c["cdn_transport"] in ("ws", "both"):
            s["ws_backend_port"] = prev.get("ws_backend_port") or random_port("ws_backend", taken, tcp_busy)
            taken |= {s["ws_backend_port"]}
        if c["cdn_transport"] in ("xhttp", "both"):
            s["xhttp_backend_port"] = prev.get("xhttp_backend_port") or random_port("xhttp_backend", taken, tcp_busy)
            taken |= {s["xhttp_backend_port"]}

    panel_public = not c["panel_private"]
    http_validation = c["cert_mode"] == "http-01"
    tcp_public: List[int] = []
    if c["profile"] in WEBSITE_PROFILES:
        tcp_public += [https_port] + ([80] if http_validation else [])
    else:
        tcp_public.append(s["reality_port"])
        if c["domain"]:
            tcp_public += [https_port] + ([80] if http_validation else [])
    if panel_public:
        tcp_public.append(s["panel_port"])
        if s["sub_port"]:
            tcp_public.append(s["sub_port"])
        if c.get("panel_domain") and http_validation:
            tcp_public.append(80)
    tcp_public += [s[f"{kind}_port"] for kind in c["extra_protocols"]]
    if s.get("exit_port"):
        tcp_public.append(s["exit_port"])
    s["public_tcp"] = sorted(set(tcp_public))
    s["public_udp"] = [s["hy2_port"]] if s["hy2_port"] else []

    check_final_plan(c, s, listeners)
    return {
        "state": s,
        "previous_public_tcp": prev.get("public_tcp", []),
        "previous_public_udp": prev.get("public_udp", []),
        "panel_public": panel_public,
        "cert_domains": cert_domains(c),
    }


def check_final_plan(c: Dict[str, Any], s: Dict[str, Any], listeners: List[Dict[str, Any]]) -> None:
    """Check the resolved plan: defaults and stored ports included, before anything is changed."""
    tcp = {"SSH": c["ssh_port"], "panel": s["panel_port"], "proxy": s["reality_port"],
           "subscription": s.get("sub_port"), "VMess": s.get("vmess_port"), "Trojan": s.get("trojan_port"),
           "WebSocket backend": s.get("ws_backend_port"), "XHTTP backend": s.get("xhttp_backend_port"),
           "exit": s.get("exit_port")}
    if c["profile"] in WEBSITE_PROFILES:
        tcp["website backend"] = c["web_backend_port"]
    elif c["domain"]:
        tcp["HTTPS"] = c["https_port"]
    if c["hy2_masquerade"]:
        tcp["masquerade backend"] = c["web_backend_port"] + 1
    if c["profile"] in WEBSITE_PROFILES or c["domain"]:
        tcp["HTTP/ACME"] = 80
    seen: Dict[int, str] = {}
    for label, port in tcp.items():
        if not port:
            continue
        if port in seen:
            raise DeploymentError(f"Port {port}/tcp is planned for both {seen[port]} and {label}.")
        seen[port] = label
    for label, port in (("subscription", s.get("sub_port")), ("VMess", s.get("vmess_port")),
                        ("Trojan", s.get("trojan_port")), ("exit", s.get("exit_port"))):
        foreign = provision.foreign_users(listeners, "tcp", port) if port else []
        if foreign:
            raise DeploymentError(f"{label} port {port}/tcp is already used by: {', '.join(foreign)}")


def web_conflicts(c: Dict[str, Any], listeners: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """
    Return (units_to_stop, blocking_messages) for ports 80/443 (and the web backend port).
    Unknown or non-web owners always block; known web servers are stopped only with explicit consent.
    """
    checks: List[Tuple[int, Tuple[str, ...]]] = []
    if c["profile"] in WEBSITE_PROFILES:
        checks = [(c["https_port"], ()), (80, ("nginx",)), (c["web_backend_port"], ("nginx",))]
    elif c["domain"]:
        checks = [(c["https_port"], ())] + ([(80, ())] if c["cert_mode"] == "http-01" else [])
    elif c["panel_domain"]:
        checks = [(80, ())] if c["cert_mode"] == "http-01" else []
    units, blocking = [], []
    for port, allowed in checks:
        for proc in provision.foreign_users(listeners, "tcp", port, allowed):
            unit = provision.KNOWN_WEB_UNITS.get(proc)
            if c["profile"] in WEBSITE_PROFILES and proc == "nginx":
                blocking.append(f"nginx already serves TCP {port}; move existing sites to "
                                f"127.0.0.1:{c['web_backend_port']} or use another IP")
            elif unit and c["stop_conflicting_services"]:
                units.append(unit)
            else:
                hint = " (re-run with --stop-conflicting-services to stop and disable it)" if unit else ""
                blocking.append(f"TCP {port} is used by '{proc}'{hint}")
    return sorted(set(units)), blocking


def build_inbounds(c: Dict[str, Any], s: Dict[str, Any], cert: Optional[Tuple[str, str]],
                   hy2_cert: Optional[Tuple[str, str]], hy2_pin: Optional[str] = None) -> List[Dict[str, Any]]:
    identity = {"email": s["email"], "uuid": s["client_uuid"], "sub_id": s["sub_id"], "node_pass": s["node_pass"]}
    inbounds = []
    if c["profile"] == "vision-tls":
        if not cert:
            raise DeploymentError("Profile 'vision-tls' needs a certificate, but none was issued.")
        inbounds.append(vision_tls_inbound(identity, s["reality_port"], c["domain"], cert[0], cert[1],
                                           c["web_backend_port"]))
    elif c["profile"] == "reality-self":
        inbounds.append(reality_inbound(identity, s["reality_port"], f"127.0.0.1:{c['web_backend_port']}", [c["domain"]],
                                        s["reality_private_key"], s["reality_public_key"],
                                        s["reality_short_id"], xver=1))
        if s.get("ws_backend_port"):
            inbounds.append(ws_local_inbound(identity, s["ws_backend_port"], s["ws_path"]))
        if s.get("xhttp_backend_port"):
            inbounds.append(xhttp_local_inbound(identity, s["xhttp_backend_port"], s["xhttp_path"]))
    else:
        if c["domain"] and cert and c["cdn_transport"] == "xhttp":
            inbounds.append(xhttp_tls_inbound(identity, c["https_port"], c["domain"], s["xhttp_path"], cert[0], cert[1]))
        elif c["domain"] and cert:
            inbounds.append(ws_inbound(identity, c["https_port"], c["domain"], s["ws_path"], cert[0], cert[1]))
        inbounds.append(reality_inbound(identity, s["reality_port"], f"{c['reality_sni']}:443", [c["reality_sni"]],
                                        s["reality_private_key"], s["reality_public_key"], s["reality_short_id"]))
    if s["hy2_port"] and hy2_cert:
        server_name = c["domain"] if cert and hy2_cert == cert else c["ip"]
        masquerade = f"http://127.0.0.1:{c['web_backend_port'] + 1}" if c["hy2_masquerade"] else None
        inbounds.append(hy2_inbound(identity, s["hy2_port"], server_name, hy2_cert[0], hy2_cert[1],
                                    s["obfs_password"] if c["hy2_obfs"] else None, hy2_pin, masquerade))
    if "vmess" in c["extra_protocols"]:
        tls = (c["domain"], cert[0], cert[1]) if c["domain"] and cert else (None, None, None)
        inbounds.append(vmess_ws_inbound(identity, s["vmess_port"], s["vmess_path"], *tls))
    if "trojan" in c["extra_protocols"]:
        if not cert:
            raise DeploymentError("Trojan needs a certificate, but none was issued.")
        inbounds.append(trojan_inbound(identity, s["trojan_port"], c["domain"], cert[0], cert[1]))
    if s.get("exit_port"):
        if c["profile"] == "reality-self":
            target, names, xver = f"127.0.0.1:{c['web_backend_port']}", [c["domain"]], 1
        else:
            target, names, xver = f"{c['reality_sni']}:443", [c["reality_sni"]], 0
        inbounds.append(reality_inbound(identity, s["exit_port"], target, names, s["reality_private_key"],
                                        s["reality_public_key"], s["reality_short_id"], xver=xver, tag="exit"))
    return inbounds


def build_nodes(c: Dict[str, Any], s: Dict[str, Any], cert_ok: bool, hy2_pin: Optional[str]) -> List[Dict[str, Any]]:
    prefix = c["node_prefix"]
    nodes = []
    if c["profile"] == "vision-tls":
        nodes.append(vision_tls_node(prefix, s["client_uuid"], c["domain"], s["reality_port"]))
    elif c["profile"] == "reality-self":
        nodes.append(reality_node(prefix, s["client_uuid"], c["domain"], s["reality_port"], c["domain"],
                                  s["reality_public_key"], s["reality_short_id"]))
    else:
        nodes.append(reality_node(prefix, s["client_uuid"], c["ip"], s["reality_port"], c["reality_sni"],
                                  s["reality_public_key"], s["reality_short_id"]))
    if s["hy2_port"]:
        hy2_args = {"obfs_password": s["obfs_password"] if c["hy2_obfs"] else None,
                    "up_mbps": c["hy2_up"], "down_mbps": c["hy2_down"]}
        if hy2_pin:
            nodes.append(hy2_node(prefix, s["node_pass"], c["ip"], s["hy2_port"], pin_sha256=hy2_pin, **hy2_args))
        else:
            nodes.append(hy2_node(prefix, s["node_pass"], c["ip"], s["hy2_port"], sni=c["domain"], **hy2_args))
    clean_ips = clean_ips_for(c["client_isp"], c["https_port"])
    cdn_host = c["cdn_domain"] or (c["domain"] if c["profile"] in ("unified", "legacy") else None)
    if cdn_host and cert_ok:
        if c["cdn_transport"] in ("ws", "both"):
            nodes += cdn_nodes(prefix, s["client_uuid"], cdn_host, s["ws_path"], clean_ips,
                               None if c["cdn_domain"] else c["ipv6_domain"], port=c["https_port"])
        if c["cdn_transport"] in ("xhttp", "both"):
            nodes += xhttp_nodes(prefix, s["client_uuid"], cdn_host, s["xhttp_path"], clean_ips, port=c["https_port"])
    if "vmess" in c["extra_protocols"]:
        tls = bool(c["domain"] and cert_ok)
        nodes.append(vmess_ws_node(f"{prefix}-vmess", s["client_uuid"], c["domain"] if tls else c["ip"],
                                   s["vmess_port"], s["vmess_path"], host=c["domain"] if tls else None, tls=tls))
    if "trojan" in c["extra_protocols"]:
        nodes.append(trojan_node(f"{prefix}-trojan", s["node_pass"], c["domain"], s["trojan_port"], sni=c["domain"]))
    if s.get("exit_port"):
        server, sni = (c["domain"], c["domain"]) if c["profile"] == "reality-self" else (c["ip"], c["reality_sni"])
        nodes.append(reality_node(prefix, s["client_uuid"], server, s["exit_port"], sni, s["reality_public_key"],
                                  s["reality_short_id"], name=f"{prefix}-exit", route="residential"))
    if c["exit_all"]:
        for node in nodes:
            node["route"] = "residential"
    for relay in c["relays"]:
        nodes.append(relay_reality_node(relay["name"], relay["server"], int(relay["port"]), nodes[0]))
    for proxy in c["residential"]:
        nodes.append(residential_socks5_node(proxy["name"], proxy["server"], int(proxy["port"]),
                                             proxy["username"], proxy["password"]))
    return nodes


# ---------------------------------------------------------------------------
# Remote execution
# ---------------------------------------------------------------------------

def _save_state(remote, state: Dict[str, Any]) -> None:
    remote.run(provision.save_state_command(), input=json.dumps(state, indent=2), name="save deployment state")


def _load_state(remote, path: str = provision.STATE_FILE, name: str = "load deployment state") -> Dict[str, Any]:
    raw = remote.run(provision.load_state_command(path), name=name).stdout.strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        raise DeploymentError(f"{path} is corrupt; fix or remove it before re-running.")


def _print_plan(c: Dict[str, Any], plan: Dict[str, Any]) -> None:
    s = plan["state"]
    print(f"    Profile            : {c['profile']}")
    print(f"    Target host        : {c['ssh_user']}@{c['ip']}:{c['ssh_port']}")
    if c.get("panel_domain"):
        panel_desc = f"public HTTPS via {c['panel_domain']}"
    elif plan["panel_public"]:
        panel_desc = f"public HTTP on {c['ip']}"
    else:
        panel_desc = "loopback + SSH tunnel"
    print(f"    Panel              : {c['ip'] if plan['panel_public'] else '127.0.0.1'}:{s['panel_port']} ({panel_desc})")
    if s.get("sub_port"):
        print(f"    Subscription       : {s['sub_port']}")
    print(f"    {'Vision TLS' if c['profile'] == 'vision-tls' else 'REALITY':<19}: {s['reality_port']}"
          + (f" -> target 127.0.0.1:{c['web_backend_port']} (Nginx website)" if c['profile'] in WEBSITE_PROFILES
             else f" -> target {c['reality_sni']}:443"))
    print(f"    Hysteria 2 (UDP)   : {s['hy2_port'] or 'disabled'}")
    print(f"    Public TCP / UDP   : {s['public_tcp']} / {s['public_udp']}")
    if plan["cert_domains"]:
        print(f"    Certificate SANs   : {', '.join(plan['cert_domains'])}")


def deploy_vps(cfg: Dict[str, Any], dry_run: bool = False, remote=None) -> Dict[str, Any]:
    c = normalize_config(cfg)
    print(f"[*] Target server: {c['ip']}:{c['ssh_port']} (user {c['ssh_user']}, profile {c['profile']})")

    if dry_run:
        plan = build_plan(c)
        print("[!] DRY-RUN: input validated; no remote action taken. Server-side state, existing "
              "listeners and stored secrets are not consulted, so ports below are provisional.")
        _print_plan(c, plan)
        s = plan["state"]
        return {"status": "dry_run_success", "ip": c["ip"], "profile": c["profile"], "domain": c["domain"],
                "panel_port": s["panel_port"], "reality_port": s["reality_port"], "hy2_port": s["hy2_port"],
                "public_tcp": s["public_tcp"], "public_udp": s["public_udp"], "cert_domains": plan["cert_domains"],
                "output_dir": c["output_dir"]}

    remote = remote or SSHTarget(c["ip"], c["ssh_port"], c["ssh_user"], c["ssh_pass"], c["ssh_key"],
                                 c["ssh_known_hosts"])
    notes: List[str] = []

    # Phase 1: preflight (read-only)
    print("[*] Phase 1: Preflight inspection...")
    info, listeners = provision.parse_preflight(remote.run_script("preflight", provision.preflight_script(),
                                                                  timeout=30).stdout)
    print(f"[+] {info.get('OS', 'unknown OS')} ({info.get('ARCH', '?')})")
    committed = _load_state(remote) if info.get("STATE") == "1" else {}
    pending = (_load_state(remote, provision.PENDING_STATE_FILE, "load pending state")
               if info.get("PENDING") == "1" else {})
    # A failed attempt may have opened ports and created keys. Reuse them and clean up its firewall rules.
    state = {**pending, **committed}
    if state:
        state["public_tcp"] = sorted(set(committed.get("public_tcp", [])) | set(pending.get("public_tcp", [])))
        state["public_udp"] = sorted(set(committed.get("public_udp", [])) | set(pending.get("public_udp", [])))
    if info.get("XUI") == "1" and not state and not c["adopt_existing_panel"]:
        raise DeploymentError("3X-UI is already installed but not managed by this skill. Re-run with "
                              "--adopt-existing-panel to let the skill set panel credentials and manage "
                              "its own 'vps-skill-*' inbounds (other inbounds are left untouched).")
    elif info.get("XUI") == "1" and not state:
        print("[+] Existing unmanaged 3X-UI detected; adopting it safely.")
    units, blocking = web_conflicts(c, listeners)
    if blocking:
        raise DeploymentError("Port conflicts detected; nothing was changed:\n  - " + "\n  - ".join(blocking))
    plan = build_plan(c, state, listeners)
    s = plan["state"]
    _print_plan(c, plan)
    _save_state(remote, s)

    if c["manage_dns"]:
        print("[*] Cloudflare DNS records...")
        records = cloudflare_dns.planned_records(c)
        for change in cloudflare_dns.ensure_records(c["cf_token"], records):
            print(f"[+] DNS: {change}")
        for _, name, content, proxied in records:
            if not proxied and not cloudflare_dns.wait_for_dns(name, content):
                notes.append(f"{name} was not visible on a public resolver yet.")

    # Phase 2: base system, optional service stop, firewall
    print("[*] Phase 2: Packages, BBR and firewall...")
    if units:
        remote.run_script("stop conflicting services", provision.stop_units_script(units))
        notes.append(f"Stopped and disabled on request: {', '.join(units)}")
    prep = parse_kv(remote.run_script("system preparation",
                                      provision.prep_script(["nginx"] if c["profile"] in WEBSITE_PROFILES else []),
                                      timeout=900).stdout)
    fw = parse_kv(remote.run_script("firewall", provision.firewall_script(
        s["public_tcp"], s["public_udp"], plan["previous_public_tcp"], plan["previous_public_udp"])).stdout)
    notes.append(f"BBR: {prep.get('BBR', 'unknown')}; firewall backend: {fw.get('FIREWALL', 'unknown')}"
                 + ("" if fw.get("FIREWALL") != "iptables" or fw.get("FIREWALL_PERSISTED")
                    else " (rules not persisted: install iptables-persistent/netfilter-persistent)"))

    # Phase 3: certificates (+ website for reality-self)
    cert: Optional[Tuple[str, str]] = None
    nginx_version = ""
    if c["profile"] in WEBSITE_PROFILES:
        nginx_version = remote.run("nginx -v 2>&1 | sed -n 's#.*nginx/\\([0-9.]*\\).*#\\1#p'",
                                   name="nginx version").stdout.strip()
        remote.run_script("nginx bootstrap", web_profile.nginx_bootstrap_script(
            web_profile.render_nginx_conf(plan["cert_domains"], c["web_backend_port"], nginx_version),
            plan["cert_domains"]))
    if plan["cert_domains"]:
        primary = plan["cert_domains"][0]
        print(f"[*] Phase 3: Certificate for {', '.join(plan['cert_domains'])}...")
        cert_dir = f"{CERT_ROOT}/{primary}"
        reload_cmd = ("systemctl reload nginx" if c["profile"] == "reality-self"
                      else "systemctl restart x-ui 2>/dev/null || true")  # Xray owns the certificate otherwise
        if c["cert_mode"] == "dns-01":
            script = provision.cert_script(plan["cert_domains"], cert_dir, "dns", reload_cmd,
                                           email=c["acme_email"], cf_token=c["cf_token"])
        elif c["profile"] in WEBSITE_PROFILES:
            script = provision.cert_script(plan["cert_domains"], cert_dir, "webroot", reload_cmd,
                                           webroot=web_profile.ACME_ROOT, email=c["acme_email"])
        else:
            script = provision.cert_script(plan["cert_domains"], cert_dir, "standalone", reload_cmd,
                                           email=c["acme_email"])
        status = parse_kv(remote.run_script("certificate issuance", script, timeout=300).stdout)
        cert = (f"{cert_dir}/fullchain.pem", f"{cert_dir}/privkey.pem")
        print(f"[+] Certificate {status.get('CERT_STATUS', 'ok')}: {cert[0]}")
    if c["profile"] == "vision-tls":
        remote.run_script("website deployment", web_profile.nginx_apply_script(
            web_profile.render_http_backend(plan["cert_domains"], c["web_backend_port"]),
            web_profile.render_site(c["site_title"], c["site_description"])))
    elif c["profile"] == "reality-self":
        remote.run_script("website deployment", web_profile.nginx_apply_script(
            web_profile.render_nginx_conf(plan["cert_domains"], c["web_backend_port"], nginx_version, *cert,
                                          ws_path=s["ws_path"] if s.get("ws_backend_port") else None,
                                          ws_port=s.get("ws_backend_port"),
                                          xhttp_path=s["xhttp_path"] if s.get("xhttp_backend_port") else None,
                                          xhttp_port=s.get("xhttp_backend_port"),
                                          plain_port=c["web_backend_port"] + 1 if c["hy2_masquerade"] else None),
            web_profile.render_site(c["site_title"], c["site_description"])))

    hy2_cert, hy2_pin = None, None
    if s["hy2_port"]:
        if cert and c["domain"]:
            hy2_cert = cert
        else:
            out = parse_kv(remote.run_script("Hysteria 2 certificate", provision.hy2_self_signed_script(c["ip"])).stdout)
            hy2_pin = out.get("HY2_PIN")
            if not hy2_pin:
                raise DeploymentError("Could not create the pinned Hysteria 2 certificate.")
            hy2_cert = (f"{provision.HY2_SELF_SIGNED_DIR}/cert.pem", f"{provision.HY2_SELF_SIGNED_DIR}/key.pem")
            notes.append("Hysteria 2 uses a self-signed certificate pinned by SHA-256 in the link/YAML; "
                         "clients without pinning support cannot verify it.")

    # Phase 4: 3X-UI installation and REALITY keys
    print(f"[*] Phase 4: 3X-UI installation/configuration (panel port {s['panel_port']})...")
    remote.run_script("3X-UI installation", provision.xui_install_script(
        s["panel_user"], s["panel_pass"], s["panel_port"], s["panel_base_path"],
        c["xui_version"], c["reinstall_xui"]), timeout=900)
    remote.run_script("Xray compatibility check", provision.ensure_compatible_xray_script())
    if not s.get("reality_private_key") or not s.get("reality_public_key"):
        priv, pub = provision.parse_x25519(remote.run_script("REALITY key generation", provision.x25519_script()).stdout)
        if not priv or not pub:
            raise DeploymentError("Failed to parse REALITY X25519 keys from `xray x25519` output.")
        s["reality_private_key"], s["reality_public_key"] = priv, pub
        _save_state(remote, s)

    # Phase 5: inbound configuration (conflict-checked, backed up, transactional)
    print("[*] Phase 5: Applying skill-owned inbounds...")
    if c.get("panel_domain") and cert:
        settings = {"webListen": "", "webDomain": c["panel_domain"], "webCertFile": cert[0], "webKeyFile": cert[1]}
    elif plan["panel_public"]:
        settings = {"webListen": "", "subListen": "", "webDomain": ""}
    else:
        settings = {"webListen": "127.0.0.1", "subListen": "127.0.0.1", "webDomain": ""}
    if s["sub_port"]:
        settings.update({"subEnable": "true", "subClashEnable": "true", "subPort": str(s["sub_port"])})
    inbounds = build_inbounds(c, s, cert, hy2_cert, hy2_pin)
    identity = {"email": s["email"], "uuid": s["client_uuid"], "sub_id": s["sub_id"], "node_pass": s["node_pass"]}
    outbound = exit_outbound(c["exit_proxy"]) if c["exit_proxy"] else None
    res = remote.run_python("inbound configuration", REMOTE_DB_SCRIPT,
                            build_db_payload(identity, inbounds, settings, outbound=outbound,
                                             exit_all=c["exit_all"]), check=False)
    db = last_json_line(res.stdout) or {}
    if not db.get("ok"):
        detail = db.get("error") or (res.stderr.strip()[-400:] or "no output")
        if db.get("conflicts"):
            detail += ": " + ", ".join(f"inbound #{x['id']} '{x['tag']}' on {x['port']}/{x['transport']}"
                                       for x in db["conflicts"])
        raise DeploymentError(f"Inbound configuration failed: {detail}")
    if db.get("disabled_stale"):
        notes.append(f"Disabled skill-owned inbounds no longer in the plan: {', '.join(db['disabled_stale'])}")
    if db.get("backup"):
        notes.append(f"Database backup before changes: {db['backup']}")

    # Phase 6: activation and verification. A rejected configuration restores the previous database.
    print("[*] Phase 6: Verifying listeners, panel login and website...")
    tcp_ports = [s["panel_port"]] + [i["port"] for i in inbounds if i["transport"] == "tcp"]
    if s["sub_port"]:
        tcp_ports.append(s["sub_port"])
    udp_ports = [i["port"] for i in inbounds if i["transport"] == "udp"]
    try:
        remote.run(provision.restart_xui_command(), name="restart x-ui")
        remote.run_script("listener verification", provision.verify_listeners_script(tcp_ports, udp_ports), timeout=60)
        if c["profile"] in WEBSITE_PROFILES:
            remote.run_script("website check", web_profile.site_check_script(c["domain"], s["reality_port"]))
            print(f"[+] Port {s['reality_port']} serves the website to non-REALITY clients.")
    except DeploymentError as e:
        if db.get("backup"):
            remote.run(provision.restore_db_command(db["backup"]), check=False, name="restore panel database")
            raise DeploymentError(f"{e}\nThe previous panel database was restored.")
        raise
    prefer_http = not bool(c.get("panel_domain"))
    probe_res = remote.run_python("panel login verification", REMOTE_PROBE_SCRIPT, {
        "port": s["panel_port"], "base_path": s["panel_base_path"], "user": s["panel_user"],
        "password": s["panel_pass"], "host": c["panel_domain"] if c.get("panel_domain") else None,
        "prefer_http": prefer_http,
    }, check=False)
    probe = last_json_line(probe_res.stdout) or {}
    if not probe.get("ok"):
        err_msg = f"{probe.get('stage', '?')}: {probe.get('msg') or probe_res.stderr.strip()[-300:]}"
        if c.get("fail_closed"):
            raise DeploymentError("Panel login verification failed (credentials were not reset): "
                                  f"{err_msg}. If two-factor authentication is enabled on this panel, log in manually.")
        else:
            print(f"[!] Warning: Panel login verification could not verify credentials automatically: {err_msg}")
            notes.append(f"Panel login probe warning: {err_msg}. Listeners passed; verify the panel manually.")
    elif not probe.get("api_verified"):
        notes.append("Panel login succeeded but the authenticated API check did not; verify the panel manually.")
    remote.run(provision.commit_state_command(), name="commit deployment state")
    units = ["x-ui"] + (["nginx"] if c["profile"] in WEBSITE_PROFILES else [])
    remote.run_script("boot self-check", boot_check.install_script(
        units, tcp_ports, udp_ports, provision.firewall_script(s["public_tcp"], s["public_udp"])))
    notes.append("Boot self-check enabled: services, firewall and ports are verified after every reboot. "
                 f"Result: {boot_check.STATUS}")

    # Phase 7: local artifacts (only after every check passed)
    print("[*] Phase 7: Writing local artifacts...")
    return _write_artifacts(c, plan, s, cert is not None, hy2_pin, probe, notes, db.get("sub_paths") or {})


def subscription_urls(c: Dict[str, Any], plan: Dict[str, Any], s: Dict[str, Any], paths: Dict[str, str]) -> Dict[str, str]:
    """The panel's own subscription: same links, no third-party service."""
    if not (s.get("sub_port") and plan["panel_public"] and paths.get("subPath")):
        return {}
    base = f"http://{c['ip']}:{s['sub_port']}"
    urls = {"url": f"{base}{paths['subPath']}{s['sub_id']}"}
    if paths.get("subClashPath"):
        urls["clash_url"] = f"{base}{paths['subClashPath']}{s['sub_id']}"
    return urls


def _write_artifacts(c, plan, s, cert_ok, hy2_pin, probe, notes, sub_paths=None) -> Dict[str, Any]:
    out_dir = secure_dir(c["output_dir"])
    nodes = build_nodes(c, s, cert_ok, hy2_pin)
    files = {}
    for node in nodes:
        if node["qr"]:
            png = os.path.join(out_dir, f"qr_{node['name']}.png")
            node["ascii_qr"] = generate_qr(node["uri"], png)
            os.chmod(png, 0o600)
            files[f"QR {node['name']}"] = png

    clash_path = write_secret(os.path.join(out_dir, "clash_config.yaml"),
                              generate_local_clash_yaml(nodes, lang=c["lang"]))
    files["Clash YAML"] = clash_path
    # Residential entries hold a paid account, so they never go to a third-party converter.
    shareable = [n["uri"] for n in nodes if n["route"] != "residential"]
    online_subs = list(build_subscription_urls(shareable)) if c["online_sub"] else []
    subscription = subscription_urls(c, plan, s, sub_paths or {})
    if c["residential"]:
        notes.append("Residential entries are client-side nodes. Use 'exit_proxy' to exit through a "
                     "residential proxy from the server instead.")
    if c["profile"] in ("unified", "legacy"):
        notes.append(f"REALITY forwards unauthenticated connections to {c['reality_sni']}:443. Consider "
                     "profile 'reality-self' (own domain + website on 443).")

    scheme = probe.get("scheme", "http")
    if c.get("panel_domain"):
        panel_url = f"https://{c['panel_domain']}:{s['panel_port']}{s['panel_base_path']}"
        notes.append(f"Panel access restricted to domain {c['panel_domain']} on port {s['panel_port']} "
                     "(direct IP access blocked with 403 Forbidden).")
    elif plan["panel_public"]:
        panel_url = f"{scheme}://{c['ip']}:{s['panel_port']}{s['panel_base_path']}"
    else:
        panel_url = f"{scheme}://127.0.0.1:{s['panel_port']}{s['panel_base_path']}"
    tunnel = f"ssh -N -L {s['panel_port']}:127.0.0.1:{s['panel_port']} -p {c['ssh_port']} {c['ssh_user']}@{c['ip']}"
    panel = {"url": panel_url, "user": s["panel_user"], "pass": s["panel_pass"], "public": plan["panel_public"],
             "tunnel": tunnel, "api_verified": bool(probe.get("api_verified"))}

    report_path = os.path.join(out_dir, f"vps_{c['ip']}_info.txt")
    result_path = os.path.join(out_dir, "result.json")
    files = {"Report": report_path, "Result JSON": result_path, **files}
    ctx = {
        "ip": c["ip"], "ipv6": c["ipv6"], "domain": c["domain"], "profile": c["profile"],
        "client_isp": c["client_isp"], "client_location": c["client_location"], "client_ip": c["client_ip"],
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "ssh_port": c["ssh_port"], "ssh_user": c["ssh_user"], "panel": panel, "nodes": nodes,
        "online_subs": online_subs, "files": files, "notes": notes, "subscription": subscription,
    }
    write_secret(report_path, render_report(ctx, c["lang"]))
    result = {
        "status": "success",
        "profile": c["profile"],
        "ip": c["ip"],
        "domain": c["domain"],
        "ipv6_domain": c["ipv6_domain"],
        "panel": panel,
        "ports": {"panel": s["panel_port"], "reality": s["reality_port"], "hy2": s["hy2_port"],
                  "subscription": s.get("sub_port"), "public_tcp": s["public_tcp"], "public_udp": s["public_udp"]},
        "subscription": subscription,
        "nodes": [{"name": n["name"], "route": n["route"], "uri": n["uri"]} for n in nodes],
        "online_subscriptions": online_subs,
        "files": files,
        "notes": notes,
    }
    write_secret_json(result_path, result)
    print(f"[+] Deployment complete. Artifacts (owner-only) in {out_dir}")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_lxc_config(path: str, container: Optional[str]) -> Dict[str, Any]:
    """Ports and access for one container, from the result.json written by vps-lxc-skill."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            containers = json.load(f).get("containers", [])
    except (OSError, ValueError) as e:
        raise DeploymentError(f"Could not read {path}: {e}")
    names = [item.get("name") for item in containers]
    for item in containers:
        if item.get("name") == container:
            return dict(item.get("deployer_config") or {})
    raise DeploymentError(f"Container '{container}' is not in {path}. Available: {', '.join(map(str, names))}")


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="VPS Multi-Protocol Deployment Automation Engine")
    parser.add_argument("--config", help="Path to JSON configuration file")
    parser.add_argument("--from-lxc", help="result.json from vps-lxc-skill, used with --container")
    parser.add_argument("--container", help="Container name inside the --from-lxc file")
    parser.add_argument("--ip", help="Server IPv4 address")
    parser.add_argument("--ssh-port", type=int, help="SSH port (default 22)")
    parser.add_argument("--ssh-user", help="SSH username (default root)")
    parser.add_argument("--ssh-pass", help="SSH password (prefer the VPS_SSH_PASS env var or --config)")
    parser.add_argument("--ssh-key", help="Path to SSH private key file")
    parser.add_argument("--ssh-known-hosts", help="known_hosts file with the verified server key (disables TOFU)")
    parser.add_argument("--profile", choices=PROFILES, help="Deployment profile (default unified; legacy is an alias)")
    parser.add_argument("--domain", help="Domain (legacy: Cloudflare-proxied for WS; reality-self: DNS-only)")
    parser.add_argument("--cdn-domain", help="reality-self: Cloudflare-proxied hostname sharing the HTTPS port")
    parser.add_argument("--cdn-transport", choices=CDN_TRANSPORTS,
                        help="CDN transport (default: both for reality-self, ws otherwise)")
    parser.add_argument("--manage-dns", action="store_true", default=None,
                        help="Create or update the Cloudflare records. Needs a token with Zone: DNS: Edit")
    parser.add_argument("--exit-port", type=int, help="Port of the inbound that exits through exit_proxy")
    parser.add_argument("--exit-all", action="store_true", default=None,
                        help="Send every inbound through exit_proxy and block QUIC, for a fully residential node")
    parser.add_argument("--hy2-masquerade", action="store_true", default=None,
                        help="reality-self: answer non-Hysteria HTTP/3 with the website. Needs --no-hy2-obfs")
    parser.add_argument("--hy2-obfs", action=argparse.BooleanOptionalAction, default=None,
                        help="Use Salamander obfuscation for Hysteria 2 (default: on)")
    parser.add_argument("--cert-mode", choices=CERT_MODES, help="Certificate validation (default http-01)")
    parser.add_argument("--cf-token", help="Cloudflare API token for dns-01 (prefer the CF_TOKEN env var)")
    parser.add_argument("--https-port", type=int, help="Public HTTPS port (default 443)")
    parser.add_argument("--web-backend-port", type=int, help=f"reality-self loopback website port (default {DEFAULT_BACKEND_PORT})")
    parser.add_argument("--extra-protocols", help="Comma-separated opt-in inbounds: vmess,trojan")
    parser.add_argument("--vmess-port", type=int, help="Override VMess-WS TCP port")
    parser.add_argument("--trojan-port", type=int, help="Override Trojan-TLS TCP port")
    parser.add_argument("--sub-port", type=int, help=f"3X-UI subscription port (default {DEFAULT_SUB_PORT})")
    parser.add_argument("--sub", dest="enable_sub", action=argparse.BooleanOptionalAction, default=None,
                        help="Publish the 3X-UI built-in subscription (default: on)")
    parser.add_argument("--hy2-up", type=int, help="Hysteria 2 client upload Mbps; set with --hy2-down to use Brutal")
    parser.add_argument("--hy2-down", type=int, help="Hysteria 2 client download Mbps; set with --hy2-up to use Brutal")
    parser.add_argument("--ipv6", help="Server IPv6 address")
    parser.add_argument("--ipv6-domain", help="IPv6 domain for an extra CDN node (legacy only)")
    parser.add_argument("--panel-domain", help="Expose the panel publicly over HTTPS on this DNS-only domain")
    parser.add_argument("--reality-sni", help=f"REALITY target/SNI for the legacy profile (default {DEFAULT_REALITY_SNI})")
    parser.add_argument("--client-isp", choices=sorted(CARRIER_CLEAN_IPS), help="Client carrier (default unicom)")
    parser.add_argument("--client-ip", help="Client outbound IP (report only)")
    parser.add_argument("--client-location", help="Client location (report only)")
    parser.add_argument("--output-dir", help="Local output directory (default ./output/<ip>)")
    parser.add_argument("--lang", choices=["en", "zh"], help="Report language (default en)")
    parser.add_argument("--panel-port", type=int, help="Override 3X-UI panel port")
    parser.add_argument("--hy2-port", type=int, help="Override Hysteria 2 UDP port")
    parser.add_argument("--reality-port", type=int, help="Override REALITY TCP port (legacy profile)")
    parser.add_argument("--hy2", dest="enable_hy2", action=argparse.BooleanOptionalAction, default=None,
                        help="Enable Hysteria 2 (default: on for legacy, off for reality-self)")
    parser.add_argument("--node-prefix", help="Prefix for node names (default 'srv')")
    parser.add_argument("--site-title", help="Website title (reality-self)")
    parser.add_argument("--acme-email", help="Optional ACME account email")
    parser.add_argument("--xui-version", help="Pin a 3X-UI release tag, e.g. v3.11.0")
    parser.add_argument("--reinstall-xui", action="store_true", default=None, help="Re-run the 3X-UI installer")
    parser.add_argument("--panel-private", action="store_true", default=None,
                        help="Restrict panel to 127.0.0.1 (SSH tunnel access only)")
    parser.add_argument("--adopt-existing-panel", action=argparse.BooleanOptionalAction, default=None,
                        help="Manage a 3X-UI installation that was not set up by this skill (default: on)")
    parser.add_argument("--stop-conflicting-services", action=argparse.BooleanOptionalAction, default=None,
                        help="Stop and disable web servers occupying required ports (default: on)")
    parser.add_argument("--rotate-secrets", action="store_true", default=None,
                        help="Generate new UUID, passwords and REALITY keys (invalidates old client links)")
    parser.add_argument("--online-sub", action=argparse.BooleanOptionalAction, default=None,
                        help="Also print third-party converter subscription URLs (default: on)")
    parser.add_argument("--fail-closed", action="store_true", default=None,
                        help="Strict fail-closed mode: abort without artifacts on verification failure")
    parser.add_argument("--dry-run", action="store_true", help="Validate and plan without remote actions")
    args = parser.parse_args(argv)

    try:
        cfg = load_lxc_config(args.from_lxc, args.container) if args.from_lxc else {}
        if args.config:
            with open(args.config, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        for key, value in vars(args).items():
            if key not in ("config", "dry_run", "from_lxc", "container") and value is not None:
                cfg[key] = value
        if not cfg.get("ssh_pass") and os.environ.get("VPS_SSH_PASS"):
            cfg["ssh_pass"] = os.environ["VPS_SSH_PASS"]
        if not cfg.get("cf_token") and os.environ.get("CF_TOKEN"):
            cfg["cf_token"] = os.environ["CF_TOKEN"]
        deploy_vps(cfg, dry_run=args.dry_run)
    except DeploymentError as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
