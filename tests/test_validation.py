"""Test input validation logic."""
import pytest
from scripts.vps_deployer import validate_config, DeploymentError


def test_valid_minimal_config():
    cfg = {"ip": "198.51.100.1", "ssh_pass": "secure_password"}
    validate_config(cfg)  # Should not raise


def test_valid_ssh_key_config():
    cfg = {"ip": "198.51.100.1", "ssh_key": "/path/to/key"}
    validate_config(cfg)  # Should not raise


def test_missing_ip():
    cfg = {"ssh_pass": "secure_password"}
    with pytest.raises(DeploymentError, match="Missing required parameter: 'ip'"):
        validate_config(cfg)


def test_invalid_ipv4():
    cfg = {"ip": "999.1.2.3", "ssh_pass": "secure_password"}
    with pytest.raises(DeploymentError, match="Invalid IPv4 address"):
        validate_config(cfg)


def test_missing_credentials():
    cfg = {"ip": "198.51.100.1"}
    with pytest.raises(DeploymentError, match="Missing authentication credentials"):
        validate_config(cfg)


def test_invalid_port():
    cfg = {"ip": "198.51.100.1", "ssh_pass": "123", "ssh_port": 99999}
    with pytest.raises(DeploymentError, match="Invalid SSH port"):
        validate_config(cfg)


def test_null_optional_fields():
    cfg = {
        "ip": "198.51.100.1",
        "ssh_pass": "123",
        "domain": None,
        "ipv6": None,
        "ipv6_domain": None,
        "client_isp": None
    }
    validate_config(cfg)  # Should not raise


def test_valid_ipv6():
    cfg = {
        "ip": "198.51.100.1",
        "ssh_pass": "123",
        "ipv6": "2001:db8:85a3::8a2e:370:7334"
    }
    validate_config(cfg)


def test_invalid_ipv6():
    cfg = {
        "ip": "198.51.100.1",
        "ssh_pass": "123",
        "ipv6": "not-an-ipv6"
    }
    with pytest.raises(DeploymentError, match="Invalid IPv6 address format"):
        validate_config(cfg)



@pytest.mark.parametrize("key,value", [
    ("domain", "a.com;rm -rf /"),
    ("domain", "bad domain.com"),
    ("panel_domain", "$(id).example.com"),
    ("reality_sni", "x"),
])
def test_rejects_shell_sensitive_hostnames(key, value):
    with pytest.raises(DeploymentError, match=f"Invalid {key}"):
        validate_config({"ip": "198.51.100.1", "ssh_pass": "x", key: value})


@pytest.mark.parametrize("extra,match", [
    ({"panel_port": 70000}, "Invalid panel_port"),
    ({"reality_port": 443}, "collides with the HTTPS port"),
    ({"panel_port": 25000, "reality_port": 25000}, "collides with panel_port"),
    ({"panel_pass": "short"}, "Invalid panel_pass"),
    ({"panel_pass": "has space in it"}, "Invalid panel_pass"),
    ({"panel_base_path": "/a;b/"}, "Invalid panel_base_path"),
    ({"profile": "nope"}, "Invalid profile"),
    ({"profile": "reality-self"}, "requires 'domain'"),
    ({"client_isp": "cable"}, "Invalid client_isp"),
    ({"xui_version": "latest; id"}, "Invalid xui_version"),
])
def test_rejects_invalid_options(extra, match):
    with pytest.raises(DeploymentError, match=match):
        validate_config(dict({"ip": "198.51.100.1", "ssh_pass": "x"}, **extra))


def test_accepts_reality_self_with_domain():
    validate_config({"ip": "198.51.100.1", "ssh_pass": "x", "profile": "reality-self", "domain": "WWW.Example.com"})
