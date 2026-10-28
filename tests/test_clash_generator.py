"""Test local Clash configuration generator."""
import yaml
from scripts.clash_generator import generate_local_clash_yaml


def test_clash_yaml_structure():
    proxies = [{
        "name": "Node-Test",
        "type": "vless",
        "server": "198.51.100.1",
        "port": 443,
        "uuid": "00000000-0000-0000-0000-000000000001",
        "network": "ws",
        "tls": True
    }]
    yaml_str = generate_local_clash_yaml(proxies)
    parsed = yaml.safe_load(yaml_str)
    assert parsed["port"] == 7890
    assert len(parsed["proxies"]) == 1
    assert parsed["proxies"][0]["name"] == "Node-Test"
    assert "rules" in parsed
