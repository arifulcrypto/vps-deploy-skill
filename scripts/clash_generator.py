#!/usr/bin/env python3
"""
Local Offline Clash Configuration Generator:
Builds production-grade Clash / Mihomo YAML configurations locally
without sending sensitive node credentials to third-party web converters.
"""
import yaml
from typing import List, Dict, Any


def generate_local_clash_yaml(
    proxies: List[Dict[str, Any]],
    output_filepath: str = None
) -> str:
    """
    Generate a complete Clash configuration with domestic DIRECT routing
    and proxy groups.
    """
    proxy_names = [p["name"] for p in proxies]
    if not proxy_names:
        proxy_names = ["DIRECT"]

    config = {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": True,
        "mode": "Rule",
        "log-level": "info",
        "external-controller": "127.0.0.1:9090",
        "dns": {
            "enable": True,
            "ipv6": False,
            "default-nameserver": ["223.5.5.5", "119.29.29.29"],
            "enhanced-mode": "fake-ip",
            "fake-ip-range": "198.18.0.1/16",
            "nameserver": [
                "https://doh.pub/dns-query",
                "https://dns.alidns.com/dns-query"
            ],
            "fallback": [
                "https://1.1.1.1/dns-query",
                "https://dns.google/dns-query"
            ]
        },
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "PROXY",
                "type": "select",
                "proxies": proxy_names + ["DIRECT"]
            },
            {
                "name": "AUTO-FALLBACK",
                "type": "fallback",
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
                "proxies": proxy_names
            }
        ],
        "rules": [
            "DOMAIN-SUFFIX,local,DIRECT",
            "IP-CIDR,127.0.0.0/8,DIRECT",
            "IP-CIDR,172.16.0.0/12,DIRECT",
            "IP-CIDR,192.168.0.0/16,DIRECT",
            "IP-CIDR,10.0.0.0/8,DIRECT",
            "IP-CIDR,100.64.0.0/10,DIRECT",
            "IP-CIDR,198.18.0.0/16,DIRECT",
            "GEOIP,CN,DIRECT",
            "MATCH,PROXY"
        ]
    }

    yaml_str = yaml.dump(config, allow_unicode=True, sort_keys=False)

    if output_filepath:
        with open(output_filepath, "w", encoding="utf-8") as f:
            f.write(yaml_str)

    return yaml_str


if __name__ == "__main__":
    sample_proxy = [{
        "name": "Sample-Node",
        "type": "vless",
        "server": "198.51.100.1",
        "port": 443,
        "uuid": "00000000-0000-0000-0000-000000000001",
        "network": "ws",
        "tls": True,
        "servername": "node.example.com",
        "ws-opts": {"path": "/ws"}
    }]
    content = generate_local_clash_yaml(sample_proxy)
    print("Sample local Clash YAML generated (length):", len(content))
