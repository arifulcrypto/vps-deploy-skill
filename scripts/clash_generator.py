#!/usr/bin/env python3
"""
Local Offline Clash Configuration Generator:
Builds Clash / Mihomo YAML locally without sending node credentials to
third-party converters. Grouping uses explicit route metadata, never node names.
Provides commercial-grade features (unified-delay, dedicated e-commerce/TikTok, AI groups),
and strictly isolates metered residential / home broadband relay nodes from auto-latency testing.
"""
from typing import Any, Dict, List, Optional

import yaml

GROUP_NAMES = {
    "en": {
        "main": "🚀 Proxy",
        "auto": "⚡ Auto (latency)",
        "fallback": "🛟 Failover",
        "direct": "🔥 Direct nodes",
        "cdn": "🛡️ CDN nodes",
        "relay": "🏠 Residential & Relay",
        "tk": "🛒 E-Commerce & TikTok",
        "ai": "🤖 AI Services",
    },
    "zh": {
        "main": "🚀 节点选择",
        "auto": "⚡ 自动选择 (低延迟)",
        "fallback": "🛟 故障转移",
        "direct": "🔥 直连节点",
        "cdn": "🛡️ CDN 节点",
        "relay": "🏠 住宅与家宽专线",
        "tk": "🛒 外贸与TikTok",
        "ai": "🤖 AI与ChatGPT",
    },
}
PROBE_URL = "https://www.gstatic.com/generate_204"
CN_DNS = ["https://dns.alidns.com/dns-query", "https://doh.pub/dns-query"]
REMOTE_DNS = ["https://1.1.1.1/dns-query", "https://dns.google/dns-query"]
GEO_BASE = "https://testingcf.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release"
# Minimum client: Mihomo v1.19.9 for REALITY with the Xray in 3X-UI v3.11.0 (v1.19.8 fails).


def generate_local_clash_yaml(nodes: List[Dict[str, Any]], output_filepath: Optional[str] = None,
                              lang: str = "en") -> str:
    """
    nodes: items from scripts.nodes ({"clash": {...}, "route": "direct"|"cdn"|"relay"|"residential"})
    or bare Clash proxy dicts (treated as route 'direct').
    """
    g = GROUP_NAMES.get(lang, GROUP_NAMES["en"])
    proxies, direct, cdn, residential_relay = [], [], [], []
    for node in nodes:
        proxy = node.get("clash", node)
        route = node.get("route", "direct")
        proxies.append(proxy)
        if route == "cdn":
            cdn.append(proxy["name"])
        elif route in ("residential", "relay"):
            residential_relay.append(proxy["name"])
        else:
            direct.append(proxy["name"])

    datacenter_nodes = direct + cdn
    all_names = datacenter_nodes + residential_relay

    groups: List[Dict[str, Any]] = []

    # 1. Main Selector. Group references must stay acyclic: Mihomo rejects the whole file otherwise.
    main_options = [g["auto"], g["fallback"]] if datacenter_nodes else []
    if residential_relay:
        main_options.append(g["relay"])
    if direct and cdn:
        main_options += [g["direct"], g["cdn"]]
    main_options += all_names + ["DIRECT"]
    groups.append({"name": g["main"], "type": "select", "proxies": main_options})

    # 2/3. Periodic probes use datacenter nodes only, so these groups are omitted when none exist.
    # Probing residential/relay nodes would burn metered traffic and drop sticky sessions.
    if datacenter_nodes:
        groups.append({
            "name": g["auto"],
            "type": "url-test",
            "url": PROBE_URL,
            "interval": 300,
            "tolerance": 50,
            "proxies": datacenter_nodes,
        })
        groups.append({
            "name": g["fallback"],
            "type": "fallback",
            "url": PROBE_URL,
            "interval": 300,
            "proxies": datacenter_nodes,
        })

    # 4. Dedicated Residential & Relay Group (manual select, zero periodic probing)
    if residential_relay:
        groups.append({
            "name": g["relay"],
            "type": "select",
            "proxies": residential_relay + ["DIRECT"],
        })

    # 5. Dedicated E-Commerce / TikTok Group
    if residential_relay:
        tk_proxies = [g["relay"]] + residential_relay + (direct or datacenter_nodes) + [g["main"]]
    else:
        tk_proxies = (direct or all_names) + [g["main"]]
    groups.append({"name": g["tk"], "type": "select", "proxies": tk_proxies})

    # 6. Dedicated AI / ChatGPT Group
    if residential_relay:
        ai_proxies = [g["relay"]] + residential_relay + [g["main"]] + datacenter_nodes
    else:
        ai_proxies = [g["main"]] + all_names
    if datacenter_nodes:
        ai_proxies.append(g["auto"])
    groups.append({"name": g["ai"], "type": "select", "proxies": ai_proxies})

    # 7. Sub-groups if both direct and cdn exist
    if direct and cdn:
        groups.append({"name": g["direct"], "type": "select", "proxies": direct})
        groups.append({"name": g["cdn"], "type": "select", "proxies": cdn})

    config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "bind-address": "127.0.0.1",
        "mode": "rule",
        "log-level": "info",
        "unified-delay": True,
        "tcp-concurrent": True,
        "find-process-mode": "off",
        "geodata-loader": "memconservative",
        "geo-auto-update": True,
        "geo-update-interval": 168,
        "geox-url": {
            "geoip": f"{GEO_BASE}/geoip.dat",
            "geosite": f"{GEO_BASE}/geosite.dat",
            "mmdb": f"{GEO_BASE}/country-lite.mmdb",
        },
        "external-controller": "127.0.0.1:9090",
        "sniffer": {
            "enable": True,
            "sniff": {"HTTP": {"ports": [80, "8080-8880"]}, "TLS": {"ports": [443, 8443]}, "QUIC": {"ports": [443, 8443]}},
        },
        # Chinese domains resolve at home. Everything else stays on the proxy, so foreign
        # lookups never reach a domestic resolver and add no local DNS delay.
        "dns": {
            "enable": True,
            "ipv6": False,
            "default-nameserver": ["223.5.5.5", "119.29.29.29"],
            "enhanced-mode": "fake-ip",
            "fake-ip-range": "198.18.0.1/16",
            "fake-ip-filter": ["*.lan", "*.local", "+.msftconnecttest.com", "+.msftncsi.com", "time.*.com", "ntp.*.com"],
            "respect-rules": True,
            "nameserver": REMOTE_DNS,
            "proxy-server-nameserver": CN_DNS,
            "nameserver-policy": {"geosite:cn,private": CN_DNS},
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
            f"DOMAIN-SUFFIX,tiktok.com,{g['tk']}",
            f"DOMAIN-SUFFIX,byteoversea.com,{g['tk']}",
            f"DOMAIN-SUFFIX,ibytedtos.com,{g['tk']}",
            f"DOMAIN-KEYWORD,tiktok,{g['tk']}",
            f"DOMAIN-SUFFIX,paypal.com,{g['tk']}",
            f"DOMAIN-SUFFIX,stripe.com,{g['tk']}",
            f"DOMAIN-SUFFIX,openai.com,{g['ai']}",
            f"DOMAIN-SUFFIX,chatgpt.com,{g['ai']}",
            f"DOMAIN-SUFFIX,oaistatic.com,{g['ai']}",
            f"DOMAIN-SUFFIX,oaiusercontent.com,{g['ai']}",
            f"DOMAIN-SUFFIX,anthropic.com,{g['ai']}",
            f"DOMAIN-SUFFIX,claude.ai,{g['ai']}",
            f"DOMAIN-SUFFIX,gemini.google.com,{g['ai']}",
            "DOMAIN-SUFFIX,cn,DIRECT",
            "GEOSITE,cn,DIRECT",
            "GEOIP,CN,DIRECT,no-resolve",
            f"MATCH,{g['main']}",
        ],
    }
    yaml_str = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
    if output_filepath:
        with open(output_filepath, "w", encoding="utf-8") as f:
            f.write(yaml_str)
    return yaml_str
