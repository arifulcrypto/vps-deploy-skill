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

