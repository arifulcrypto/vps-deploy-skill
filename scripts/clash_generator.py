#!/usr/bin/env python3
"""
Local Offline Clash Configuration Generator:
Builds Clash / Mihomo YAML locally without sending node credentials to
third-party converters. Grouping uses explicit route metadata, never node names.
"""
from typing import Any, Dict, List, Optional

import yaml

GROUP_NAMES = {
    "en": {"main": "🚀 Proxy", "auto": "⚡ Auto (latency)", "fallback": "🛟 Failover",
           "direct": "🔥 Direct nodes", "cdn": "🛡️ CDN nodes"},
    "zh": {"main": "🚀 节点选择", "auto": "⚡ 自动选择 (低延迟)", "fallback": "🛟 故障转移",
           "direct": "🔥 直连节点", "cdn": "🛡️ CDN 节点"},
}
PROBE_URL = "https://www.gstatic.com/generate_204"


def generate_local_clash_yaml(nodes: List[Dict[str, Any]], output_filepath: Optional[str] = None,
                              lang: str = "en") -> str:
    """
    nodes: items from scripts.nodes ({"clash": {...}, "route": "direct"|"cdn"}) or bare Clash
    proxy dicts (treated as route 'direct').
    """
    g = GROUP_NAMES.get(lang, GROUP_NAMES["en"])
    proxies, direct, cdn = [], [], []
    for node in nodes:
        proxy = node.get("clash", node)
        route = node.get("route", "direct")
        proxies.append(proxy)
        (cdn if route == "cdn" else direct).append(proxy["name"])
    names = direct + cdn

    groups: List[Dict[str, Any]] = []
    main = [g["auto"], g["fallback"]]
    if direct and cdn:
        main += [g["direct"], g["cdn"]]
    main += names + ["DIRECT"]
    groups.append({"name": g["main"], "type": "select", "proxies": main})
    groups.append({"name": g["auto"], "type": "url-test", "url": PROBE_URL, "interval": 300, "tolerance": 50,
                   "proxies": names or ["DIRECT"]})
    # Failover tries direct nodes first and falls back to CDN nodes when they are unreachable.
    groups.append({"name": g["fallback"], "type": "fallback", "url": PROBE_URL, "interval": 300,
                   "proxies": names or ["DIRECT"]})
    if direct and cdn:
        groups.append({"name": g["direct"], "type": "select", "proxies": direct})
        groups.append({"name": g["cdn"], "type": "select", "proxies": cdn})

    config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "bind-address": "127.0.0.1",
        "mode": "rule",
        "log-level": "info",
        "external-controller": "127.0.0.1:9090",
        "dns": {
            "enable": True,
            "ipv6": False,
            "default-nameserver": ["223.5.5.5", "119.29.29.29"],
            "enhanced-mode": "fake-ip",
            "fake-ip-range": "198.18.0.1/16",
            "nameserver": ["https://doh.pub/dns-query", "https://dns.alidns.com/dns-query"],
            "fallback": ["https://1.1.1.1/dns-query", "https://dns.google/dns-query"],
        },
        "proxies": proxies,
        "proxy-groups": groups,
        "rules": [
            "DOMAIN-SUFFIX,local,DIRECT",
            "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
            "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
            "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,100.64.0.0/10,DIRECT,no-resolve",
            "IP-CIDR,198.18.0.0/16,DIRECT,no-resolve",
            "GEOIP,CN,DIRECT",
            f"MATCH,{g['main']}",
        ],
    }
    yaml_str = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
    if output_filepath:
        with open(output_filepath, "w", encoding="utf-8") as f:
            f.write(yaml_str)
    return yaml_str
