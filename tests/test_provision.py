"""Provisioning script builders: shell syntax, quoting and output parsers."""
import subprocess

import pytest

from scripts import provision, web_profile


def bash_syntax_ok(script):
    return subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True).returncode == 0


@pytest.mark.parametrize("script", [
    provision.preflight_script(),
    provision.prep_script(["nginx"]),
    provision.stop_units_script(["nginx", "apache2"]),
    provision.firewall_script([80, 443, 23456], [34567], [22222], [33333]),
    provision.cert_script(["a.example.com", "b.example.com"], "/root/cert/a.example.com", "standalone", "true"),
    provision.cert_script(["a.example.com"], "/root/cert/a.example.com", "webroot", "systemctl reload nginx",
                          webroot="/var/www/acme", email="ops@example.com"),
    provision.hy2_self_signed_script("198.51.100.1"),
    provision.xui_install_script("user", "p'a\"ss$(id)`x`", 50000, "/abc/", "v3.11.0"),
    provision.x25519_script(),
    provision.verify_listeners_script([443, 50000], [30000]),
    web_profile.nginx_apply_script(web_profile.render_nginx_conf(["www.example.com"], 8443, "1.26.0", "/c", "/k"),
                                   web_profile.render_site("Title", "Desc")),
    web_profile.site_check_script("www.example.com"),
])
def test_generated_scripts_parse(script):
    assert bash_syntax_ok(script)


def test_panel_password_is_shell_quoted():
    script = provision.xui_install_script("user", "p'a\"ss$(id)", 50000, "/abc/")
    assert "-password 'p'\"'\"'a\"ss$(id)'" in script


def test_firewall_removes_only_stale_ports_and_uses_dedicated_chain():
    script = provision.firewall_script([443, 25000], [31000], stale_tcp=[443, 24000], stale_udp=[30000])
    assert 'STALE="24000/tcp 30000/udp"' in script
    assert 'WANTED="443/tcp 25000/tcp 31000/udp"' in script
    assert '-F VPS_SKILL' in script and '-C INPUT -j VPS_SKILL' in script


def test_cert_script_has_no_self_signed_fallback():
    script = provision.cert_script(["a.example.com"], "/root/cert/a.example.com", "standalone", "true")
    assert "openssl req" not in script and "exit 11" in script and "check_cert ||" in script


def test_parse_listeners_and_ownership():
    ss = (
        'tcp   LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=10,fd=6),("nginx",pid=11,fd=6))\n'
        'tcp   LISTEN 0 4096 *:443 *:* users:(("xray-linux-amd64",pid=20,fd=3))\n'
        'udp   UNCONN 0 0 [::]:30000 [::]:* users:(("xray-linux-arm64",pid=20,fd=9))\n'
        'tcp   LISTEN 0 128 127.0.0.1:631 0.0.0.0:*\n'
    )
    listeners = provision.parse_listeners(ss)
    assert provision.port_users(listeners, "tcp", 80) == ["nginx"]
    assert provision.foreign_users(listeners, "tcp", 443) == []
    assert provision.foreign_users(listeners, "tcp", 80) == ["nginx"]
    assert provision.foreign_users(listeners, "tcp", 80, allowed=["nginx"]) == []
    assert provision.foreign_users(listeners, "tcp", 631) == ["?"]
    assert provision.port_users(listeners, "udp", 30000) == ["xray-linux-arm64"]


@pytest.mark.parametrize("output,expected", [
    ("Private key: PRIV1\nPublic key: PUB1\n", ("PRIV1", "PUB1")),
    ("PrivateKey: PRIV2\nPassword: PUB2\nHash32: HASH\n", ("PRIV2", "PUB2")),
    ("PrivateKey: PRIV3\nPassword (PublicKey): PUB3\n", ("PRIV3", "PUB3")),
    ("command not found", ("", "")),
])
def test_parse_x25519_versions(output, expected):
    assert provision.parse_x25519(output) == expected


def test_nginx_conf_adapts_to_version():
    new = web_profile.render_nginx_conf(["www.example.com"], 8443, "1.26.2", "/c", "/k")
    assert "http2 on;" in new and "ssl_reject_handshake on;" in new
    assert "listen 127.0.0.1:8443 ssl proxy_protocol;" in new
    old = web_profile.render_nginx_conf(["www.example.com"], 8443, "1.18.0", "/c", "/k")
    assert "http2 on;" not in old and "ssl http2 proxy_protocol" in old and "ssl_reject_handshake" not in old
    bootstrap = web_profile.render_nginx_conf(["www.example.com"], 8443, "1.26.2")
    assert "8443" not in bootstrap and "acme-challenge" in bootstrap


def test_site_content_is_escaped():
    site = web_profile.render_site("<script>x</script>", "a & b")
    assert "<script>x" not in site["index.html"] and "&lt;script&gt;" in site["index.html"]
