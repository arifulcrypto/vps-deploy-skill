#!/usr/bin/env python3
"""
Provisioning Script Builders:
Pure functions that render the bash scripts executed on the target, plus parsers
for their output. Every interpolated value is validated upstream or shell-quoted here.
"""
import re
import shlex
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

STATE_DIR = "/etc/vps-skill"
STATE_FILE = f"{STATE_DIR}/state.json"
HY2_SELF_SIGNED_DIR = f"{STATE_DIR}/hy2"
XUI_BIN = "/usr/local/x-ui/x-ui"
XUI_INSTALL_URL = "https://raw.githubusercontent.com/MHSanaei/3x-ui/{ref}/install.sh"

# Processes that belong to a skill-managed 3X-UI installation
OWNED_PROCESS_PREFIXES = ("x-ui", "xray-linux-")
# Web servers we know how to stop when the operator explicitly allows it
KNOWN_WEB_UNITS = {"nginx": "nginx", "apache2": "apache2", "httpd": "httpd", "caddy": "caddy", "lighttpd": "lighttpd"}

q = shlex.quote


# ---------------------------------------------------------------------------
# Preflight & listener analysis
# ---------------------------------------------------------------------------

def preflight_script() -> str:
    return f"""
. /etc/os-release 2>/dev/null; echo "OS=${{PRETTY_NAME:-unknown}}"
echo "ARCH=$(uname -m)"
[ -x {XUI_BIN} ] && echo XUI=1 || echo XUI=0
[ -s {STATE_FILE} ] && echo STATE=1 || echo STATE=0
command -v python3 >/dev/null 2>&1 && echo PY=1 || echo PY=0
command -v nginx >/dev/null 2>&1 && echo "NGINX=$(nginx -v 2>&1 | sed -n 's#.*nginx/\\([0-9.]*\\).*#\\1#p')" || echo NGINX=
echo "---LISTENERS---"
ss -Htulnp 2>/dev/null || true
"""


def parse_preflight(stdout: str) -> Tuple[Dict[str, str], List[Dict[str, object]]]:
    head, _, tail = stdout.partition("---LISTENERS---")
    info = {}
    for line in head.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info, parse_listeners(tail)


def parse_listeners(ss_output: str) -> List[Dict[str, object]]:
    """Parse `ss -Htulnp` lines into {proto, port, addr, procs}."""
    listeners = []
    for line in ss_output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] not in ("tcp", "udp"):
            continue
        local = parts[4]
        addr, _, port = local.rpartition(":")
        if not port.isdigit():
            continue
        procs = sorted(set(re.findall(r'\("([^"]+)"', line)))
        listeners.append({"proto": parts[0], "port": int(port), "addr": addr, "procs": procs})
    return listeners


def is_owned_process(name: str) -> bool:
    return any(name.startswith(p) for p in OWNED_PROCESS_PREFIXES)


def port_users(listeners: Sequence[Dict[str, object]], proto: str, port: int) -> List[str]:
    """Process names listening on proto/port ('?' when ss could not attribute it)."""
    users = []
    for entry in listeners:
        if entry["proto"] == proto and entry["port"] == port:
            users.extend(entry["procs"] or ["?"])
    return sorted(set(users))


def foreign_users(listeners, proto: str, port: int, allowed: Iterable[str] = ()) -> List[str]:
    """Listeners on proto/port that are neither skill-owned nor explicitly allowed."""
    allowed = set(allowed)
    return [p for p in port_users(listeners, proto, port) if not is_owned_process(p) and p not in allowed]


# ---------------------------------------------------------------------------
# Base system preparation
# ---------------------------------------------------------------------------

def prep_script(extra_packages: Sequence[str] = ()) -> str:
    extra = " ".join(q(p) for p in extra_packages)
    return f"""
set -e
if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y >/dev/null </dev/null
    apt-get install -y curl socat cron python3 openssl iproute2 {extra} >/dev/null </dev/null
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y curl socat cronie python3 openssl iproute {extra} >/dev/null </dev/null
elif command -v yum >/dev/null 2>&1; then
    yum install -y curl socat cronie python3 openssl iproute {extra} >/dev/null </dev/null
else
    echo "Unsupported distribution: need apt-get, dnf or yum" >&2
    exit 1
fi

# Persist BBR (container kernels may refuse; that is reported, not fatal)
if modprobe tcp_bbr 2>/dev/null || grep -qw bbr /proc/sys/net/ipv4/tcp_available_congestion_control 2>/dev/null; then
    printf 'net.core.default_qdisc=fq\\nnet.ipv4.tcp_congestion_control=bbr\\n' > /etc/sysctl.d/99-vps-skill.conf
    sysctl -p /etc/sysctl.d/99-vps-skill.conf >/dev/null 2>&1 || true
fi
echo "BBR=$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null || echo unknown)"
"""


def stop_units_script(units: Sequence[str]) -> str:
    names = " ".join(q(u) for u in units)
    return f"""
for u in {names}; do
    systemctl stop "$u" || {{ echo "failed to stop $u" >&2; exit 1; }}
    systemctl disable "$u" >/dev/null 2>&1 || true
    echo "STOPPED=$u"
done
"""


# ---------------------------------------------------------------------------
# Firewall (idempotent, managed rules only)
# ---------------------------------------------------------------------------

def firewall_script(tcp: Sequence[int], udp: Sequence[int], stale_tcp: Sequence[int] = (),
                    stale_udp: Sequence[int] = ()) -> str:
    """
    Open exactly the planned ports and remove ports this skill opened on a previous run.
    ufw/firewalld rules are added idempotently; with plain iptables all rules live in a
    dedicated VPS_SKILL chain that is flushed and rebuilt on every run.
    """
    wanted = [f"{int(p)}/tcp" for p in sorted(set(tcp))] + [f"{int(p)}/udp" for p in sorted(set(udp))]
    stale = [f"{int(p)}/tcp" for p in sorted(set(stale_tcp) - set(tcp))] + \
            [f"{int(p)}/udp" for p in sorted(set(stale_udp) - set(udp))]
    ipt_rules = "\n".join(
        f'        "$ipt" -A VPS_SKILL -p {r.split("/")[1]} --dport {r.split("/")[0]} -j ACCEPT' for r in wanted
    )
    return f"""
WANTED="{' '.join(wanted)}"
STALE="{' '.join(stale)}"
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
    for r in $STALE; do ufw --force delete allow "$r" >/dev/null 2>&1 || true; done
    for r in $WANTED; do ufw allow "$r" comment vps-skill >/dev/null; done
    echo FIREWALL=ufw
elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    for r in $STALE; do firewall-cmd --permanent --remove-port="$r" >/dev/null 2>&1 || true; done
    for r in $WANTED; do firewall-cmd --permanent --add-port="$r" >/dev/null; done
    firewall-cmd --reload >/dev/null
    echo FIREWALL=firewalld
elif command -v iptables >/dev/null 2>&1; then
    for ipt in iptables ip6tables; do
        command -v "$ipt" >/dev/null 2>&1 || continue
        "$ipt" -N VPS_SKILL 2>/dev/null || true
        "$ipt" -F VPS_SKILL
        "$ipt" -C INPUT -j VPS_SKILL 2>/dev/null || "$ipt" -I INPUT -j VPS_SKILL
{ipt_rules}
    done
    if command -v netfilter-persistent >/dev/null 2>&1; then
        netfilter-persistent save >/dev/null 2>&1 && echo FIREWALL_PERSISTED=1
    elif command -v service >/dev/null 2>&1 && [ -f /etc/sysconfig/iptables ]; then
        service iptables save >/dev/null 2>&1 && echo FIREWALL_PERSISTED=1
    fi
    echo FIREWALL=iptables
else
    echo FIREWALL=none
fi
"""


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------

def cert_check_function() -> str:
    """Shell function: valid = not self-signed, >14 days left, SAN covers every domain, key matches."""
    return """
check_cert() {
    [ -s "$FULLCHAIN" ] && [ -s "$KEY" ] || return 1
    openssl x509 -in "$FULLCHAIN" -noout -checkend 1209600 >/dev/null 2>&1 || return 1
    subj=$(openssl x509 -in "$FULLCHAIN" -noout -subject 2>/dev/null | sed 's/^subject= *//')
    iss=$(openssl x509 -in "$FULLCHAIN" -noout -issuer 2>/dev/null | sed 's/^issuer= *//')
    [ "$subj" != "$iss" ] || return 1
    sans=$(openssl x509 -in "$FULLCHAIN" -noout -text 2>/dev/null | grep -A1 'Subject Alternative Name' | tail -n1 | tr ',' '\\n' | sed 's/^ *//')
    for d in $DOMAINS; do printf '%s\\n' "$sans" | grep -qxF "DNS:$d" || return 1; done
    a=$(openssl x509 -in "$FULLCHAIN" -noout -pubkey 2>/dev/null | openssl sha256)
    b=$(openssl pkey -in "$KEY" -pubout 2>/dev/null | openssl sha256)
    [ -n "$a" ] && [ "$a" = "$b" ]
}
"""


def cert_script(domains: Sequence[str], cert_dir: str, mode: str, reload_cmd: str,
                webroot: Optional[str] = None, email: Optional[str] = None) -> str:
    """
    Ensure a publicly trusted ECC certificate covering all `domains`.
    Fails closed: there is no self-signed fallback.
    mode: 'standalone' (acme.sh binds :80) or 'webroot' (existing web server serves :80).
    """
    if mode not in ("standalone", "webroot"):
        raise ValueError("mode must be 'standalone' or 'webroot'")
    d_flags = " ".join(f"-d {q(d)}" for d in domains)
    mode_flags = "--standalone" if mode == "standalone" else f"--webroot {q(webroot or '')}"
    install_email = f"email={q(email)}" if email else ""
    return f"""
set -u
DOMAINS={q(' '.join(domains))}
CERT_DIR={q(cert_dir)}
FULLCHAIN="$CERT_DIR/fullchain.pem"
KEY="$CERT_DIR/privkey.pem"
{cert_check_function()}
if check_cert; then echo CERT_STATUS=valid; exit 0; fi

ACME="$HOME/.acme.sh/acme.sh"
if [ ! -x "$ACME" ]; then
    curl -fsSL https://get.acme.sh -o /tmp/vps-skill-acme-install.sh || {{ echo "acme.sh download failed" >&2; exit 10; }}
    sh /tmp/vps-skill-acme-install.sh {install_email} </dev/null >/dev/null || {{ echo "acme.sh install failed" >&2; exit 10; }}
    rm -f /tmp/vps-skill-acme-install.sh
fi
"$ACME" --set-default-ca --server letsencrypt >/dev/null </dev/null
"$ACME" --issue {d_flags} {mode_flags} --keylength ec-256 </dev/null
rc=$?
# 0 = issued, 2 = existing acme.sh certificate is not yet due for renewal
if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ]; then echo "acme.sh --issue failed (exit $rc); check DNS (A/AAAA, grey cloud for HTTP-01) and port 80 reachability" >&2; exit 11; fi
mkdir -p "$CERT_DIR" && chmod 700 "$CERT_DIR"
"$ACME" --install-cert -d {q(domains[0])} --ecc --fullchain-file "$FULLCHAIN" --key-file "$KEY" \\
    --reloadcmd {q(reload_cmd)} </dev/null || {{ echo "acme.sh --install-cert failed" >&2; exit 12; }}
check_cert || {{ echo "Installed certificate failed validation (trust, expiry, SAN coverage or key match)" >&2; exit 13; }}
echo CERT_STATUS=issued
"""


def hy2_self_signed_script(ip: str) -> str:
    """Self-signed certificate for bare-IP Hysteria 2, consumed by clients via SHA-256 pinning."""
    d = HY2_SELF_SIGNED_DIR
    return f"""
set -e
umask 077
mkdir -p {d}
if ! openssl x509 -in {d}/cert.pem -noout -checkend 2592000 >/dev/null 2>&1; then
    openssl ecparam -name prime256v1 -genkey -noout -out {d}/key.pem
    openssl req -new -x509 -sha256 -key {d}/key.pem -out {d}/cert.pem -days 3650 \\
        -subj "/CN={ip}" -addext "subjectAltName=IP:{ip}" >/dev/null 2>&1
fi
echo "HY2_PIN=$(openssl x509 -in {d}/cert.pem -noout -fingerprint -sha256 | cut -d= -f2)"
"""


# ---------------------------------------------------------------------------
# 3X-UI installation & keys
# ---------------------------------------------------------------------------

def xui_install_script(panel_user: str, panel_pass: str, panel_port: int, base_path: str,
                       version: Optional[str] = None, reinstall: bool = False) -> str:
    ref = version or "main"
    url = XUI_INSTALL_URL.format(ref=f"refs/tags/{version}" if version else "main")
    version_arg = q(version) if version else ""
    return f"""
set -e
if [ -x {XUI_BIN} ] && [ "{1 if reinstall else 0}" != "1" ]; then
    echo XUI_INSTALL=present
else
    curl -fsSL {q(url)} -o /tmp/vps-skill-3xui-install.sh
    XUI_NONINTERACTIVE=1 bash /tmp/vps-skill-3xui-install.sh {version_arg} </dev/null >/tmp/vps-skill-3xui-install.log 2>&1 || {{
        tail -n 20 /tmp/vps-skill-3xui-install.log >&2; exit 1; }}
    rm -f /tmp/vps-skill-3xui-install.sh
    echo XUI_INSTALL=installed:{q(ref)}
fi
[ -x {XUI_BIN} ] || {{ echo "3X-UI binary missing after install" >&2; exit 1; }}
{XUI_BIN} setting -username {q(panel_user)} -password {q(panel_pass)} >/dev/null
{XUI_BIN} setting -port {int(panel_port)} >/dev/null
{XUI_BIN} setting -webBasePath {q(base_path)} >/dev/null
echo XUI_CONFIGURED=1
"""


def x25519_script() -> str:
    return """
set -e
XRAY_BIN=$(find /usr/local/x-ui/bin/ -maxdepth 1 -name 'xray-linux-*' -type f -perm /111 2>/dev/null | head -n 1)
[ -n "$XRAY_BIN" ] || { echo "Xray binary not found under /usr/local/x-ui/bin" >&2; exit 1; }
"$XRAY_BIN" x25519
"""


def parse_x25519(stdout: str) -> Tuple[str, str]:
    """
    Parse `xray x25519` across versions:
      'Private key: / Public key:'  (older)
      'PrivateKey: / Password:'      (25.x)
      'PrivateKey: / Password (PublicKey):'
    """
    priv = re.search(r"^\s*Private\s*Key\s*:\s*(\S+)", stdout, re.IGNORECASE | re.MULTILINE)
    pub = re.search(r"^\s*(?:Public\s*Key|Password(?:\s*\(PublicKey\))?)\s*:\s*(\S+)",
                    stdout, re.IGNORECASE | re.MULTILINE)
    return (priv.group(1) if priv else "", pub.group(1) if pub else "")


# ---------------------------------------------------------------------------
# State & verification
# ---------------------------------------------------------------------------

def save_state_command() -> str:
    """Command that atomically writes stdin to the state file with 0600 permissions."""
    return (f"umask 077 && mkdir -p {STATE_DIR} && cat > {STATE_FILE}.tmp && "
            f"mv {STATE_FILE}.tmp {STATE_FILE}")


def load_state_command() -> str:
    return f"cat {STATE_FILE} 2>/dev/null || true"


def verify_listeners_script(tcp: Sequence[int], udp: Sequence[int], wait_seconds: int = 15) -> str:
    tcp_s = " ".join(str(int(p)) for p in tcp)
    udp_s = " ".join(str(int(p)) for p in udp)
    return f"""
missing=""
for i in $(seq 1 {int(wait_seconds)}); do
    missing=""
    for p in {tcp_s}; do ss -Htln "sport = :$p" | grep -q . || missing="$missing $p/tcp"; done
    for p in {udp_s}; do ss -Huln "sport = :$p" | grep -q . || missing="$missing $p/udp"; done
    [ -z "$missing" ] && break
    sleep 1
done
systemctl is-active --quiet x-ui || {{ echo "x-ui service is not active" >&2; journalctl -u x-ui -n 20 --no-pager >&2 2>/dev/null; exit 20; }}
if [ -n "$missing" ]; then
    echo "Expected listeners missing:$missing (the Xray core probably rejected the configuration)" >&2
    journalctl -u x-ui -n 20 --no-pager >&2 2>/dev/null
    exit 21
fi
echo LISTENERS=ok
"""


def restart_xui_command() -> str:
    return "systemctl restart x-ui"
