"""Nginx rendering for current and older packaged versions."""
from scripts.web_profile import DEFAULT_CERT, nginx_apply_script, nginx_bootstrap_script, render_nginx_conf


def conf(version):
    return render_nginx_conf(["www.example.com"], 8443, version, "/c/f.pem", "/c/k.pem")


def test_current_nginx_rejects_unknown_sni_during_the_handshake():
    assert "ssl_reject_handshake on;" in conf("1.24.0")


def test_older_nginx_never_shows_the_real_certificate_to_unknown_sni():
    text = conf("1.18.0")
    default_server = text.split("default_server;")[1].split("}")[0]
    assert "ssl_reject_handshake" not in text
    assert DEFAULT_CERT in default_server and "return 444;" in default_server
    assert "/c/f.pem" not in default_server
    assert "openssl req -x509" in nginx_apply_script(text)


def test_bootstrap_keeps_a_working_https_config_for_the_same_names():
    script = nginx_bootstrap_script("server {}", ["www.example.com"])
    assert script.index("echo NGINX=kept") < script.index("nginx -t")
    assert "server_name www.example.com;" in script


def test_rejected_config_restores_the_previous_file():
    script = nginx_apply_script("server {}")
    assert "the previous file was restored" in script and "vps-skill.conf.bak" in script
