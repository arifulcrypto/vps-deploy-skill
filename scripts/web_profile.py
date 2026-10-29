#!/usr/bin/env python3
"""
Website Profile (reality-self):
Xray owns public TCP 443 (VLESS + REALITY + Vision). Every connection that is not a
valid REALITY client is forwarded (with PROXY protocol) to a loopback Nginx serving
the operator's own static site with a publicly trusted certificate for the domain.
Port 80 serves ACME HTTP-01 challenges and redirects everything else to HTTPS.
"""
import html
import shlex
from typing import Dict, Optional, Sequence, Tuple

SITE_ROOT = "/var/www/vps-skill-site"
ACME_ROOT = "/var/www/vps-skill-acme"
NGINX_CONF = "/etc/nginx/conf.d/vps-skill.conf"

q = shlex.quote


def parse_version(text: Optional[str]) -> Tuple[int, ...]:
    try:
        return tuple(int(x) for x in (text or "").strip().split(".") if x != "")
    except ValueError:
        return ()


def render_nginx_conf(domains: Sequence[str], backend_port: int, nginx_version: str,
                      cert_path: Optional[str] = None, key_path: Optional[str] = None) -> str:
    """
    Without cert paths only the port-80 server is rendered (bootstrap for HTTP-01).
    """
    names = " ".join(domains)
    conf = f"""# Managed by vps-deploy-skill (reality-self profile). Changes are overwritten on redeploy.
server {{
    listen 80;
    listen [::]:80;
    server_name {names};
    server_tokens off;
    location ^~ /.well-known/acme-challenge/ {{
        root {ACME_ROOT};
        default_type text/plain;
    }}
    location / {{
        return 301 https://$host$request_uri;
    }}
}}
"""
    if not (cert_path and key_path):
        return conf

    version = parse_version(nginx_version)
    http2_directive = version >= (1, 25, 1)
    listen_opts = "ssl proxy_protocol" if http2_directive else "ssl http2 proxy_protocol"
    listen = f"127.0.0.1:{int(backend_port)}"
    reject_block = ""
    if version >= (1, 19, 4):
        reject_block = f"""
# Unknown or missing SNI: abort the handshake like most real-world HTTPS hosts.
server {{
    listen {listen} {listen_opts} default_server;
    ssl_reject_handshake on;
}}
"""
    conf += reject_block + f"""
server {{
    listen {listen} {listen_opts};
{"    http2 on;" if http2_directive else ""}
    server_name {names};
    server_tokens off;

    ssl_certificate     {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:vps_skill:10m;

    set_real_ip_from 127.0.0.1;
    real_ip_header proxy_protocol;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;

    root {SITE_ROOT};
    index index.html;
    error_page 404 /404.html;
    location / {{
        try_files $uri $uri/ =404;
    }}
}}
"""
    return conf


def render_site(title: str, description: str) -> Dict[str, str]:
    t = html.escape(title)
    d = html.escape(description)
    page = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{margin:0;font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#1f2933;background:#f7f7f5}}
main{{max-width:42rem;margin:12vh auto;padding:0 1.25rem}}
h1{{font-size:1.8rem;margin:0 0 .5rem}}
p{{color:#52606d}}
footer{{margin-top:3rem;font-size:.85rem;color:#9aa5b1}}
</style>
</head>
<body>
<main>
<h1>{heading}</h1>
<p>{body}</p>
<footer>&copy; {title}</footer>
</main>
</body>
</html>
"""
    return {
        "index.html": page.format(title=t, heading=t, body=d),
        "404.html": page.format(title=f"Not found · {t}", heading="Page not found",
                                body="The page you are looking for does not exist."),
        "robots.txt": "User-agent: *\nAllow: /\n",
    }


def write_files_script(files: Dict[str, str], mode: str = "0644") -> str:
    """Bash that writes each {path: content} via quoted heredocs (content is never shell-evaluated)."""
    parts = ["set -e"]
    for i, (path, content) in enumerate(files.items()):
        marker = f"VPS_SKILL_EOF_{i}"
        if marker in content:
            raise ValueError("file content collides with heredoc marker")
        parts.append(f"mkdir -p \"$(dirname {q(path)})\"")
        parts.append(f"cat > {q(path)} <<'{marker}'\n{content.rstrip(chr(10))}\n{marker}")
        parts.append(f"chmod {mode} {q(path)}")
    return "\n".join(parts) + "\n"


def nginx_apply_script(conf: str, site_files: Optional[Dict[str, str]] = None) -> str:
    files = {NGINX_CONF: conf}
    for name, content in (site_files or {}).items():
        files[f"{SITE_ROOT}/{name}"] = content
    return write_files_script(files) + f"""
mkdir -p {ACME_ROOT}
systemctl enable nginx >/dev/null 2>&1 || true
nginx -t 2>&1 || {{ echo "nginx -t rejected the generated configuration" >&2; exit 1; }}
if systemctl is-active --quiet nginx; then systemctl reload nginx; else systemctl start nginx; fi
echo NGINX=ok
"""


def site_check_script(domain: str) -> str:
    """A non-REALITY TLS client to public :443 must receive the deployed index page via the fallback."""
    return f"""
body=$(curl -sk --max-time 10 --resolve {q(domain)}:443:127.0.0.1 https://{q(domain)}/) || {{
    echo "HTTPS request through :443 failed (REALITY target / Nginx chain broken)" >&2; exit 30; }}
want=$(cat {SITE_ROOT}/index.html)
[ "$body" = "$want" ] || {{ echo "Port 443 did not serve the deployed website" >&2; exit 31; }}
echo SITE=ok
"""
