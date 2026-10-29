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


def test_clash_categorized_groups():
    proxies = [
        {"name": "VPS-Direct-Reality-20159", "type": "vless", "server": "1.2.3.4", "port": 20159},
        {"name": "VPS-Direct-Hy2-42972", "type": "hysteria2", "server": "1.2.3.4", "port": 42972},
        {"name": "VPS-CF-VLESS-443", "type": "vless", "server": "example.com", "port": 443},
    ]
    yaml_str = generate_local_clash_yaml(proxies)
    parsed = yaml.safe_load(yaml_str)
    group_names = [g["name"] for g in parsed["proxy-groups"]]
    assert "🚀 节点选择" in group_names
    assert "⚡ 自动优选 (低延迟)" in group_names
    assert "🔥 极速直连 (搬瓦工/三网优化)" in group_names
    assert "🛡️ CDN 兜底 (Cloudflare 防封)" in group_names
