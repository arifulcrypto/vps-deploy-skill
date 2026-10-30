#!/usr/bin/env python3
"""
VPS Deployer Unified Automation Engine:
Connects to a VPS, installs/configures 3X-UI and produces client artifacts.

Profiles
  legacy        VLESS-REALITY on a random high TCP port (external target), optional
                Hysteria 2 on a random high UDP port, and VLESS-WS-TLS on 443 for a
                Cloudflare-proxied domain.
  reality-self  Single public TCP 443: VLESS-REALITY-Vision whose target is the
                operator's own loopback HTTPS website (Nginx). Requires a DNS-only domain.

Every step fails closed: no report, links or QR codes are written unless all remote
steps, listener checks and the panel login probe succeed. Re-runs reuse the identity,
ports and keys stored on the server in /etc/vps-skill/state.json.
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

from scripts import provision, web_profile  # noqa: E402
from scripts.clash_generator import generate_local_clash_yaml  # noqa: E402
from scripts.db_configurator import (REMOTE_DB_SCRIPT, build_db_payload, hy2_inbound,  # noqa: E402
                                     reality_inbound, ws_inbound)
from scripts.nodes import CARRIER_CLEAN_IPS, cdn_nodes, hy2_node, reality_node  # noqa: E402
from scripts.panel_probe import REMOTE_PROBE_SCRIPT  # noqa: E402
from scripts.port_utils import (CLOUDFLARE_HTTPS_PORTS, generate_unambiguous_password,  # noqa: E402
                                normalize_base_path, random_path, random_port)
from scripts.qr_engine import generate_qr  # noqa: E402
from scripts.remote import DeploymentError, SSHTarget, last_json_line, parse_kv  # noqa: E402
from scripts.report import render_report, secure_dir, write_secret, write_secret_json  # noqa: E402
from scripts.sub_converter import build_subscription_urls  # noqa: E402

PROFILES = ("unified", "legacy", "reality-self")
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
USER_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
PATH_RE = re.compile(r"^/?[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/?$")
VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+$")
EMAIL_RE = re.compile(r"^[^@\s'\"]+@[a-z0-9.-]+\.[a-z]{2,}$")
PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
DEFAULT_REALITY_SNI = "addons.mozilla.org"
DEFAULT_BACKEND_PORT = 8443
CERT_ROOT = "/root/cert"

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

    for key in ("domain", "ipv6_domain", "panel_domain", "reality_sni"):
        value = _str(cfg, key).lower()
        if value and not DOMAIN_RE.match(value):
            raise DeploymentError(f"Invalid {key}: '{value}' is not a valid DNS hostname.")

    profile = _str(cfg, "profile") or "unified"
    if profile not in PROFILES:
        raise DeploymentError(f"Invalid profile '{profile}'. Choose one of: {', '.join(PROFILES)}")
    if profile == "reality-self" and not _str(cfg, "domain"):
        raise DeploymentError("Profile 'reality-self' requires 'domain' (a DNS-only / grey-cloud A record to this VPS).")

    isp = (_str(cfg, "client_isp") or "unicom").lower()
    if isp not in CARRIER_CLEAN_IPS:
        raise DeploymentError(f"Invalid client_isp '{isp}'. Choose one of: {', '.join(CARRIER_CLEAN_IPS)}")
    if (_str(cfg, "lang") or "en").lower() not in ("en", "zh"):
        raise DeploymentError("Invalid lang. Choose 'en' or 'zh'.")

    tcp_ports = {}
    for key in ("panel_port", "reality_port", "web_backend_port"):
        if cfg.get(key) not in (None, ""):
            tcp_ports[key] = _port(cfg[key], key)
    if cfg.get("hy2_port") not in (None, ""):
        _port(cfg["hy2_port"], "hy2_port")
    reserved = {80: "HTTP/ACME", 443: "HTTPS", int(cfg.get("ssh_port") or 22): "SSH"}
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
        "ipv6": _str(cfg, "ipv6") or None,
        "ipv6_domain": (_str(cfg, "ipv6_domain").lower() or None) if profile != "reality-self" else None,
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
        "web_backend_port": int(cfg.get("web_backend_port") or DEFAULT_BACKEND_PORT),
        "panel_user": cfg.get("panel_user") or None,
        "panel_pass": cfg.get("panel_pass") or None,
        "panel_base_path": normalize_base_path(cfg["panel_base_path"]) if cfg.get("panel_base_path") else None,
        "panel_private": _flag(cfg, "panel_private", False),
        "node_pass": cfg.get("node_pass") or None,
        "obfs_password": cfg.get("obfs_password") or None,
        "enable_hy2": _flag(cfg, "enable_hy2", profile != "reality-self"),
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
    domains = [c["domain"], c["ipv6_domain"], c["panel_domain"]]
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
    if not rotate:
        s["reality_private_key"] = prev.get("reality_private_key", "")
        s["reality_public_key"] = prev.get("reality_public_key", "")

    reserved_tcp = {80, 443, c["ssh_port"], c["web_backend_port"]}

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
        return random_port(kind, avoid, tcp_busy if proto == "tcp" else udp_busy)

    s["panel_port"] = choose("panel", "tcp", reserved_tcp)
    if c["profile"] == "reality-self":
        s["reality_port"] = 443
    else:
        s["reality_port"] = choose("reality", "tcp", reserved_tcp | {s["panel_port"]})
    s["hy2_port"] = choose("hy2", "udp", set()) if c["enable_hy2"] else None

    panel_public = not c["panel_private"]
    tcp_public: List[int] = []
    if c["profile"] == "reality-self":
        tcp_public += [80, 443]
    else:
        tcp_public.append(s["reality_port"])
        if c["domain"]:
            tcp_public += [80, 443]
    if panel_public:
        tcp_public.append(s["panel_port"])
        if c.get("panel_domain") and 80 not in tcp_public:
            tcp_public.append(80)
    s["public_tcp"] = sorted(set(tcp_public))
    s["public_udp"] = [s["hy2_port"]] if s["hy2_port"] else []

    return {
        "state": s,
        "previous_public_tcp": prev.get("public_tcp", []),
        "previous_public_udp": prev.get("public_udp", []),
        "panel_public": panel_public,
        "cert_domains": cert_domains(c),
    }


def web_conflicts(c: Dict[str, Any], listeners: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """
    Return (units_to_stop, blocking_messages) for ports 80/443 (and the web backend port).
    Unknown or non-web owners always block; known web servers are stopped only with explicit consent.
    """
    checks: List[Tuple[int, Tuple[str, ...]]] = []
    if c["profile"] == "reality-self":
        checks = [(443, ()), (80, ("nginx",)), (c["web_backend_port"], ("nginx",))]
    elif c["domain"] or c["panel_domain"]:
        checks = [(443, ()), (80, ())]
    units, blocking = [], []
    for port, allowed in checks:
        for proc in provision.foreign_users(listeners, "tcp", port, allowed):
            unit = provision.KNOWN_WEB_UNITS.get(proc)
            if c["profile"] == "reality-self" and proc == "nginx":
                blocking.append(f"nginx already serves TCP {port}; move existing sites to "
                                f"127.0.0.1:{c['web_backend_port']} or use another IP")
            elif unit and c["stop_conflicting_services"]:
                units.append(unit)
            else:
                hint = " (re-run with --stop-conflicting-services to stop and disable it)" if unit else ""
                blocking.append(f"TCP {port} is used by '{proc}'{hint}")
    return sorted(set(units)), blocking


def build_inbounds(c: Dict[str, Any], s: Dict[str, Any], cert: Optional[Tuple[str, str]],
                   hy2_cert: Optional[Tuple[str, str]]) -> List[Dict[str, Any]]:
    identity = {"email": s["email"], "uuid": s["client_uuid"], "sub_id": s["sub_id"], "node_pass": s["node_pass"]}
    inbounds = []
    if c["profile"] == "reality-self":
        inbounds.append(reality_inbound(identity, 443, f"127.0.0.1:{c['web_backend_port']}", [c["domain"]],
                                        s["reality_private_key"], s["reality_public_key"],
                                        s["reality_short_id"], xver=1))
    else:
        if c["domain"] and cert:
            inbounds.append(ws_inbound(identity, 443, c["domain"], s["ws_path"], cert[0], cert[1]))
        inbounds.append(reality_inbound(identity, s["reality_port"], f"{c['reality_sni']}:443", [c["reality_sni"]],
                                        s["reality_private_key"], s["reality_public_key"], s["reality_short_id"]))
    if s["hy2_port"] and hy2_cert:
        server_name = c["domain"] if cert and hy2_cert == cert else c["ip"]
        inbounds.append(hy2_inbound(identity, s["hy2_port"], server_name, hy2_cert[0], hy2_cert[1],
                                    s["obfs_password"] if c["hy2_obfs"] else None))
    return inbounds


def build_nodes(c: Dict[str, Any], s: Dict[str, Any], cert_ok: bool, hy2_pin: Optional[str]) -> List[Dict[str, Any]]:
    prefix = c["node_prefix"]
    nodes = []
    if c["profile"] == "reality-self":
        nodes.append(reality_node(prefix, s["client_uuid"], c["domain"], 443, c["domain"],
                                  s["reality_public_key"], s["reality_short_id"]))
    else:
        nodes.append(reality_node(prefix, s["client_uuid"], c["ip"], s["reality_port"], c["reality_sni"],
                                  s["reality_public_key"], s["reality_short_id"]))
    if s["hy2_port"]:
        obfs = s["obfs_password"] if c["hy2_obfs"] else None
        if hy2_pin:
            nodes.append(hy2_node(prefix, s["node_pass"], c["ip"], s["hy2_port"], pin_sha256=hy2_pin, obfs_password=obfs))
        else:
            nodes.append(hy2_node(prefix, s["node_pass"], c["ip"], s["hy2_port"], sni=c["domain"], obfs_password=obfs))
    if c["profile"] in ("unified", "legacy") and c["domain"] and cert_ok:
        nodes += cdn_nodes(prefix, s["client_uuid"], c["domain"], s["ws_path"],
                           CARRIER_CLEAN_IPS[c["client_isp"]], c["ipv6_domain"])
    return nodes


# ---------------------------------------------------------------------------
# Remote execution
# ---------------------------------------------------------------------------

def _save_state(remote, state: Dict[str, Any]) -> None:
    remote.run(provision.save_state_command(), input=json.dumps(state, indent=2), name="save deployment state")


def _load_state(remote) -> Dict[str, Any]:
    raw = remote.run(provision.load_state_command(), name="load deployment state").stdout.strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        raise DeploymentError("/etc/vps-skill/state.json is corrupt; fix or remove it before re-running.")


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
    print(f"    REALITY (TCP)      : {s['reality_port']}"
          + (f" -> target 127.0.0.1:{c['web_backend_port']} (Nginx website)" if c['profile'] == 'reality-self'
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
    state = _load_state(remote) if info.get("STATE") == "1" else {}
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

    # Phase 2: base system, optional service stop, firewall
    print("[*] Phase 2: Packages, BBR and firewall...")
    if units:
        remote.run_script("stop conflicting services", provision.stop_units_script(units))
        notes.append(f"Stopped and disabled on request: {', '.join(units)}")
    prep = parse_kv(remote.run_script("system preparation",
                                      provision.prep_script(["nginx"] if c["profile"] == "reality-self" else []),
                                      timeout=900).stdout)
    fw = parse_kv(remote.run_script("firewall", provision.firewall_script(
        s["public_tcp"], s["public_udp"], plan["previous_public_tcp"], plan["previous_public_udp"])).stdout)
    notes.append(f"BBR: {prep.get('BBR', 'unknown')}; firewall backend: {fw.get('FIREWALL', 'unknown')}"
                 + ("" if fw.get("FIREWALL") != "iptables" or fw.get("FIREWALL_PERSISTED")
                    else " (rules not persisted: install iptables-persistent/netfilter-persistent)"))

    # Phase 3: certificates (+ website for reality-self)
    cert: Optional[Tuple[str, str]] = None
    nginx_version = ""
    if c["profile"] == "reality-self":
        nginx_version = remote.run("nginx -v 2>&1 | sed -n 's#.*nginx/\\([0-9.]*\\).*#\\1#p'",
                                   name="nginx version").stdout.strip()
        remote.run_script("nginx bootstrap", web_profile.nginx_apply_script(
            web_profile.render_nginx_conf(plan["cert_domains"], c["web_backend_port"], nginx_version)))
    if plan["cert_domains"]:
        primary = plan["cert_domains"][0]
        print(f"[*] Phase 3: Certificate for {', '.join(plan['cert_domains'])}...")
        cert_dir = f"{CERT_ROOT}/{primary}"
        if c["profile"] == "reality-self":
            script = provision.cert_script(plan["cert_domains"], cert_dir, "webroot", "systemctl reload nginx",
                                           webroot=web_profile.ACME_ROOT, email=c["acme_email"])
        else:
            script = provision.cert_script(plan["cert_domains"], cert_dir, "standalone",
                                           "systemctl restart x-ui 2>/dev/null || true", email=c["acme_email"])
        status = parse_kv(remote.run_script("certificate issuance", script, timeout=300).stdout)
        cert = (f"{cert_dir}/fullchain.pem", f"{cert_dir}/privkey.pem")
        print(f"[+] Certificate {status.get('CERT_STATUS', 'ok')}: {cert[0]}")
    if c["profile"] == "reality-self":
        remote.run_script("website deployment", web_profile.nginx_apply_script(
            web_profile.render_nginx_conf(plan["cert_domains"], c["web_backend_port"], nginx_version, *cert),
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
    inbounds = build_inbounds(c, s, cert, hy2_cert)
    identity = {"email": s["email"], "uuid": s["client_uuid"], "sub_id": s["sub_id"], "node_pass": s["node_pass"]}
    res = remote.run_python("inbound configuration", REMOTE_DB_SCRIPT, build_db_payload(identity, inbounds, settings),
                            check=False)
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
    remote.run(provision.restart_xui_command(), name="restart x-ui")

    # Phase 6: verification
    print("[*] Phase 6: Verifying listeners, panel login and website...")
    tcp_ports = [s["panel_port"]] + [i["port"] for i in inbounds if i["transport"] == "tcp"]
    udp_ports = [i["port"] for i in inbounds if i["transport"] == "udp"]
    remote.run_script("listener verification", provision.verify_listeners_script(tcp_ports, udp_ports), timeout=60)
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
            notes.append(f"Panel login probe warning: {err_msg}. Nodes are fully operational; verify panel manually.")
    if not probe.get("api_verified"):
        notes.append("Panel login succeeded but the authenticated API check did not; verify the panel manually.")
    if c["profile"] == "reality-self":
        remote.run_script("website check", web_profile.site_check_script(c["domain"]))
        print("[+] Port 443 serves the website to non-REALITY clients.")

    # Phase 7: local artifacts (only after every check passed)
    print("[*] Phase 7: Writing local artifacts...")
    return _write_artifacts(c, plan, s, cert is not None, hy2_pin, probe, notes)


def _write_artifacts(c, plan, s, cert_ok, hy2_pin, probe, notes) -> Dict[str, Any]:
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
    online_subs = list(build_subscription_urls([n["uri"] for n in nodes])) if c["online_sub"] else []
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
        "online_subs": online_subs, "files": files, "notes": notes,
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
                  "public_tcp": s["public_tcp"], "public_udp": s["public_udp"]},
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

def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="VPS Multi-Protocol Deployment Automation Engine")
    parser.add_argument("--config", help="Path to JSON configuration file")
    parser.add_argument("--ip", help="Server IPv4 address")
    parser.add_argument("--ssh-port", type=int, help="SSH port (default 22)")
    parser.add_argument("--ssh-user", help="SSH username (default root)")
    parser.add_argument("--ssh-pass", help="SSH password (prefer the VPS_SSH_PASS env var or --config)")
    parser.add_argument("--ssh-key", help="Path to SSH private key file")
    parser.add_argument("--ssh-known-hosts", help="known_hosts file with the verified server key (disables TOFU)")
    parser.add_argument("--profile", choices=PROFILES, help="Deployment profile (default legacy)")
    parser.add_argument("--domain", help="Domain (legacy: Cloudflare-proxied for WS; reality-self: DNS-only)")
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

    cfg: Dict[str, Any] = {}
    if args.config:
        with open(args.config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    for key, value in vars(args).items():
        if key not in ("config", "dry_run") and value is not None:
            cfg[key] = value
    if not cfg.get("ssh_pass") and os.environ.get("VPS_SSH_PASS"):
        cfg["ssh_pass"] = os.environ["VPS_SSH_PASS"]

    try:
        deploy_vps(cfg, dry_run=args.dry_run)
    except DeploymentError as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
