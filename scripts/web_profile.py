#!/usr/bin/env python3
"""
Website Profile (reality-self):
Xray owns public TCP 443 (VLESS + REALITY + Vision). Every connection that is not a
valid REALITY client is forwarded (with PROXY protocol) to a loopback Nginx serving
the operator's own static site with a publicly trusted certificate for the domain.
Port 80 serves ACME HTTP-01 challenges and redirects everything else to HTTPS.
An optional CDN hostname shares the same public port: REALITY forwards its SNI to Nginx,
which sends one secret path to a loopback Xray WebSocket inbound.
"""
import html
import shlex
from typing import Dict, Optional, Sequence, Tuple

SITE_ROOT = "/var/www/vps-skill-site"
ACME_ROOT = "/var/www/vps-skill-acme"
NGINX_CONF = "/etc/nginx/conf.d/vps-skill.conf"
DEFAULT_CERT = "/etc/vps-skill/nginx-default.crt"
DEFAULT_KEY = "/etc/vps-skill/nginx-default.key"

q = shlex.quote


def parse_version(text: Optional[str]) -> Tuple[int, ...]:
    try:
        return tuple(int(x) for x in (text or "").strip().split(".") if x != "")
    except ValueError:
        return ()


def render_nginx_conf(domains: Sequence[str], backend_port: int, nginx_version: str,
                      cert_path: Optional[str] = None, key_path: Optional[str] = None,
                      ws_path: Optional[str] = None, ws_port: Optional[int] = None,
                      xhttp_path: Optional[str] = None, xhttp_port: Optional[int] = None,
                      plain_port: Optional[int] = None) -> str:
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
    if version >= (1, 19, 4):
        reject_rule = "ssl_reject_handshake on;"
    else:
        # ssl_reject_handshake needs 1.19.4. A throwaway certificate keeps the real
        # certificate, and so the domain, away from anyone connecting without its SNI.
        reject_rule = f"ssl_certificate {DEFAULT_CERT};\n    ssl_certificate_key {DEFAULT_KEY};\n    return 444;"
    ws_block = ""
    if ws_path and ws_port:
        ws_block = f"""
    location = {ws_path} {{
        proxy_pass http://127.0.0.1:{int(ws_port)};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 300s;
    }}
"""
    if xhttp_path and xhttp_port:
        ws_block += f"""
    location ^~ {xhttp_path}/ {{
        proxy_pass http://127.0.0.1:{int(xhttp_port)};
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_request_buffering off;
        proxy_buffering off;
        client_max_body_size 0;
        proxy_read_timeout 300s;
    }}
"""
    # Hysteria masquerade cannot speak PROXY protocol, so it gets its own loopback listener.
    plain_listen = f"\n    listen 127.0.0.1:{int(plain_port)};" if plain_port else ""
    conf += f"""
# Unknown or missing SNI: abort like most real-world HTTPS hosts.
server {{
    listen {listen} {listen_opts} default_server;
    {reject_rule}
}}

server {{
    listen {listen} {listen_opts};{plain_listen}
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
{ws_block}
    location / {{
        try_files $uri $uri/ =404;
    }}
}}
"""
    return conf


def render_http_backend(domains: Sequence[str], backend_port: int) -> str:
    """vision-tls: Xray owns TLS, so Nginx serves plain HTTP on loopback behind the fallback."""
    return render_nginx_conf(domains, backend_port, "") + f"""
server {{
    listen 127.0.0.1:{int(backend_port)} proxy_protocol;
    server_name {' '.join(domains)};
    server_tokens off;

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
    default_cert = ""
    if DEFAULT_CERT in conf:
        default_cert = f"""
umask 077
mkdir -p {q(DEFAULT_CERT.rsplit('/', 1)[0])}
[ -s {DEFAULT_CERT} ] || openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 3650 \\
    -subj "/CN=localhost" -keyout {DEFAULT_KEY} -out {DEFAULT_CERT} >/dev/null 2>&1
umask 022
"""
    # The previous file stays in place until the new one passes `nginx -t`.
    return f"""
set -e
[ -f {NGINX_CONF} ] && cp -f {NGINX_CONF} {NGINX_CONF}.bak || rm -f {NGINX_CONF}.bak
""" + write_files_script(files) + default_cert + f"""
mkdir -p {ACME_ROOT}
systemctl enable nginx >/dev/null 2>&1 || true
if ! nginx -t 2>&1; then
    if [ -f {NGINX_CONF}.bak ]; then mv -f {NGINX_CONF}.bak {NGINX_CONF}; else rm -f {NGINX_CONF}; fi
    echo "nginx -t rejected the generated configuration; the previous file was restored" >&2
    exit 1
fi
rm -f {NGINX_CONF}.bak
if systemctl is-active --quiet nginx; then systemctl reload nginx; else systemctl start nginx; fi
echo NGINX=ok
"""


def nginx_bootstrap_script(conf: str, domains: Sequence[str]) -> str:
    """
    Port-80 config for the first HTTP-01 run. A working HTTPS config for the same names is kept,
    so a redeploy or renewal never takes the REALITY target offline.
    """
    names = q(f"server_name {' '.join(domains)};")
    return (f"if grep -q ssl_certificate {NGINX_CONF} 2>/dev/null && grep -qF {names} {NGINX_CONF}; then\n"
            "    echo NGINX=kept\n    exit 0\nfi\n" + nginx_apply_script(conf))


def site_check_script(domain: str, port: int = 443) -> str:
    """A non-REALITY TLS client to the public port must receive the deployed index page via the fallback."""
    port = int(port)
    return f"""
body=$(curl -sk --max-time 10 --resolve {q(domain)}:{port}:127.0.0.1 https://{q(domain)}:{port}/) || {{
    echo "HTTPS request through :{port} failed (REALITY target / Nginx chain broken)" >&2; exit 30; }}
want=$(cat {SITE_ROOT}/index.html)
[ "$body" = "$want" ] || {{ echo "Port {port} did not serve the deployed website" >&2; exit 31; }}
echo SITE=ok
"""
