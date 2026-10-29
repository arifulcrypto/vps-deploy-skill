"""End-to-end orchestration against a scripted fake remote: fail-closed behaviour and artifacts."""
import json
import os
import stat

import pytest
import yaml

from scripts.vps_deployer import DeploymentError, deploy_vps

PREFLIGHT = "OS=Debian GNU/Linux 12\nARCH=x86_64\nXUI={xui}\nSTATE={state}\nPY=1\nNGINX=\n---LISTENERS---\n{ss}"


def responses(xui=0, state=None, ss="", **overrides):
    base = {
        "preflight": (0, PREFLIGHT.format(xui=xui, state=1 if state else 0, ss=ss), ""),
        "load deployment state": (0, json.dumps(state) if state else "", ""),
        "system preparation": (0, "BBR=bbr\n", ""),
        "firewall": (0, "FIREWALL=ufw\n", ""),
        "certificate issuance": (0, "CERT_STATUS=issued\n", ""),
        "Hysteria 2 certificate": (0, "HY2_PIN=AA:BB:CC\n", ""),
        "REALITY key generation": (0, "PrivateKey: PRIVKEY\nPassword: PUBKEY\n", ""),
        "inbound configuration": (0, json.dumps({"ok": True, "inbounds": {}, "disabled_stale": [],
                                                 "backup": "/etc/x-ui/x-ui.db.vps-skill-1.bak"}), ""),
        "panel login verification": (0, json.dumps({"ok": True, "scheme": "http", "api_verified": True}), ""),
        "nginx version": (0, "1.26.0\n", ""),
    }
    base.update(overrides)
    return base


def cfg(tmp_path, **extra):
    c = {"ip": "198.51.100.1", "ssh_pass": "x", "output_dir": str(tmp_path / "out")}
    c.update(extra)
    return c


def called(remote):
    return [name for name, _ in remote.calls]


def test_legacy_with_domain_writes_complete_private_artifacts(tmp_path, fake_remote_factory):
    remote = fake_remote_factory(responses())
    result = deploy_vps(cfg(tmp_path, domain="cdn.example.com", ipv6_domain="v6.example.com"), remote=remote)

    names = [n["name"] for n in result["nodes"]]
    assert names == ["srv-reality", "srv-hy2", "srv-cdn", "srv-cdn-a", "srv-cdn-b", "srv-cdn-v6"]
    out = tmp_path / "out"
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o700
    for f in out.iterdir():
        assert stat.S_IMODE(os.stat(f).st_mode) == 0o600, f
    clash = yaml.safe_load((out / "clash_config.yaml").read_text())
    assert [p["name"] for p in clash["proxies"]] == names
    assert clash["allow-lan"] is False
    assert result["online_subscriptions"] == []
    assert result["panel"]["public"] is False and result["panel"]["url"].startswith("http://127.0.0.1:")
    assert "ssh -N -L" in (out / "vps_198.51.100.1_info.txt").read_text()
    # firewall opens only REALITY + 80/443 TCP and the Hysteria UDP port; the panel stays private
    s = result["ports"]
    assert s["public_tcp"] == sorted([80, 443, s["reality"]]) and s["public_udp"] == [s["hy2"]]
    assert s["panel"] not in s["public_tcp"]


def test_certificate_failure_aborts_before_artifacts(tmp_path, fake_remote_factory):
    remote = fake_remote_factory(responses(**{"certificate issuance": (11, "", "acme.sh --issue failed")}))
    with pytest.raises(DeploymentError, match="certificate issuance failed"):
        deploy_vps(cfg(tmp_path, domain="cdn.example.com"), remote=remote)
    assert not (tmp_path / "out").exists()
    assert "inbound configuration" not in called(remote)


def test_failed_login_probe_never_resets_credentials(tmp_path, fake_remote_factory):
    remote = fake_remote_factory(responses(**{
        "panel login verification": (1, json.dumps({"ok": False, "stage": "login", "msg": "wrong"}), "")}))
    with pytest.raises(DeploymentError, match="Panel login verification failed"):
        deploy_vps(cfg(tmp_path), remote=remote)
    assert not (tmp_path / "out").exists()
    assert called(remote).count("3X-UI installation") == 1
    assert all("resetTwoFactor" not in (payload or "") for _, payload in remote.calls)


def test_unmanaged_existing_panel_is_not_touched(tmp_path, fake_remote_factory):
    remote = fake_remote_factory(responses(xui=1))
    with pytest.raises(DeploymentError, match="adopt-existing-panel"):
        deploy_vps(cfg(tmp_path), remote=remote)
    assert called(remote) == ["preflight"]


def test_web_server_conflict_requires_explicit_consent(tmp_path, fake_remote_factory):
    ss = 'tcp LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=1,fd=6))\n'
    remote = fake_remote_factory(responses(ss=ss))
    with pytest.raises(DeploymentError, match="TCP 80 is used by 'nginx'"):
        deploy_vps(cfg(tmp_path, domain="cdn.example.com"), remote=remote)
    assert called(remote) == ["preflight"]

    remote = fake_remote_factory(responses(ss=ss))
    deploy_vps(cfg(tmp_path, domain="cdn.example.com", stop_conflicting_services=True), remote=remote)
    stop = [p for n, p in remote.calls if n == "stop conflicting services"]
    assert stop and "nginx" in stop[0] and "pkill" not in stop[0]


def test_db_conflict_is_reported(tmp_path, fake_remote_factory):
    remote = fake_remote_factory(responses(**{"inbound configuration": (3, json.dumps({
        "ok": False, "error": "port conflict with existing inbounds",
        "conflicts": [{"id": 5, "tag": "inbound-19000", "port": 19000, "transport": "tcp"}]}), "")}))
    with pytest.raises(DeploymentError, match="inbound #5 'inbound-19000'"):
        deploy_vps(cfg(tmp_path), remote=remote)
    assert "restart x-ui" not in called(remote)


def test_rerun_reuses_identity_ports_and_cleans_stale_firewall_rules(tmp_path, fake_remote_factory):
    first = fake_remote_factory(responses())
    deploy_vps(cfg(tmp_path), remote=first)
    state = json.loads([p for n, p in first.calls if n == "save deployment state"][-1])

    second = fake_remote_factory(responses(xui=1, state=dict(state, public_udp=state["public_udp"] + [39999])))
    result = deploy_vps(cfg(tmp_path), remote=second)
    new_state = json.loads([p for n, p in second.calls if n == "save deployment state"][-1])
    for key in ("client_uuid", "node_pass", "panel_pass", "reality_port", "hy2_port", "panel_port",
                "reality_private_key"):
        assert new_state[key] == state[key], key
    assert "REALITY key generation" not in called(second)
    firewall = [p for n, p in second.calls if n == "firewall"][0]
    assert 'STALE="39999/udp"' in firewall
    assert result["ports"]["hy2"] == state["hy2_port"]


def test_bare_ip_hysteria_uses_pinned_certificate(tmp_path, fake_remote_factory):
    result = deploy_vps(cfg(tmp_path), remote=fake_remote_factory(responses()))
    hy2 = [n for n in result["nodes"] if n["name"] == "srv-hy2"][0]
    assert "pinSHA256=AA%3ABB%3ACC" in hy2["uri"] and "insecure=1" in hy2["uri"]
    clash = yaml.safe_load((tmp_path / "out" / "clash_config.yaml").read_text())
    proxy = [p for p in clash["proxies"] if p["name"] == "srv-hy2"][0]
    assert proxy["fingerprint"] == "aabbcc" and proxy["skip-cert-verify"] is False


def test_reality_self_profile(tmp_path, fake_remote_factory):
    remote = fake_remote_factory(responses())
    result = deploy_vps(cfg(tmp_path, profile="reality-self", domain="www.example.com"), remote=remote)
    assert [n["name"] for n in result["nodes"]] == ["srv-reality"]
    uri = result["nodes"][0]["uri"]
    assert uri.startswith("vless://") and "@www.example.com:443?" in uri and "sni=www.example.com" in uri
    assert result["ports"]["public_tcp"] == [80, 443] and result["ports"]["public_udp"] == []
    names = called(remote)
    assert names.index("nginx bootstrap") < names.index("certificate issuance") < names.index("website deployment")
    assert "website check" in names
    cert_script = [p for n, p in remote.calls if n == "certificate issuance"][0]
    assert "--webroot /var/www/vps-skill-acme" in cert_script


def test_reality_self_refuses_nginx_on_443(tmp_path, fake_remote_factory):
    ss = 'tcp LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=1,fd=6))\n'
    remote = fake_remote_factory(responses(ss=ss))
    with pytest.raises(DeploymentError, match="nginx already serves TCP 443"):
        deploy_vps(cfg(tmp_path, profile="reality-self", domain="www.example.com",
                       stop_conflicting_services=True), remote=remote)


def test_online_converters_are_opt_in(tmp_path, fake_remote_factory):
    result = deploy_vps(cfg(tmp_path, online_sub=True), remote=fake_remote_factory(responses()))
    assert len(result["online_subscriptions"]) == 2
