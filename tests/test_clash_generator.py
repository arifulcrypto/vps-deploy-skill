"""Local Clash configuration generator and node builder."""
import yaml

from scripts.clash_generator import generate_local_clash_yaml
from scripts.nodes import (cdn_nodes, hy2_node, reality_node, relay_reality_node,
                           residential_socks5_node, trojan_node, vmess_ws_node)


def sample_nodes():
    return [reality_node("n", "uuid-1", "198.51.100.1", 443, "www.example.com", "PUB", "ab12"),
            hy2_node("n", "pw", "198.51.100.1", 31000, sni="www.example.com", obfs_password="ob")] + \
        cdn_nodes("n", "uuid-1", "cdn.example.com", "/p4th", [("104.16.160.1", "a")])



def test_bare_proxy_dicts_are_accepted():
    parsed = yaml.safe_load(generate_local_clash_yaml([{"name": "Node-Test", "type": "vless", "server": "1.2.3.4",
                                                         "port": 443, "uuid": "u"}]))
    assert parsed["proxies"][0]["name"] == "Node-Test"
    assert parsed["rules"][-1] == "MATCH,🚀 Proxy"


def test_groups_use_route_metadata_and_failover_is_reachable():
    parsed = yaml.safe_load(generate_local_clash_yaml(sample_nodes(), lang="zh"))
    groups = {g["name"]: g for g in parsed["proxy-groups"]}
    assert groups["🔥 直连节点"]["proxies"] == ["n-reality", "n-hy2"]          # 443 REALITY stays direct
    assert groups["🛡️ CDN 节点"]["proxies"] == ["n-cdn", "n-cdn-a"]
    assert "🛟 故障转移" in groups["🚀 节点选择"]["proxies"]
    assert groups["🛟 故障转移"]["proxies"][:2] == ["n-reality", "n-hy2"]
    assert not any("搬瓦工" in name for name in groups)


def test_local_only_listener_defaults():
    parsed = yaml.safe_load(generate_local_clash_yaml(sample_nodes()))
    assert parsed["allow-lan"] is False and parsed["bind-address"] == "127.0.0.1"
    assert parsed["external-controller"].startswith("127.0.0.1:")


def test_links_and_yaml_describe_the_same_nodes():
    nodes = sample_nodes()
    parsed = yaml.safe_load(generate_local_clash_yaml(nodes))
    assert [p["name"] for p in parsed["proxies"]] == [n["name"] for n in nodes]
    assert all(n["uri"].endswith("#" + n["name"]) for n in nodes)


def test_ws_path_and_ipv6_hosts_are_encoded():
    node = cdn_nodes("n", "u", "cdn.example.com", "/a b", [], None)[0]
    assert "path=%2Fa+b" in node["uri"]
    v6 = hy2_node("n", "p@ss", "2001:db8::1", 30000)
    assert "p%40ss@[2001:db8::1]:30000" in v6["uri"]


def test_residential_and_relay_isolated_from_auto_test():
    base = sample_nodes()
    # Add a relay node and a residential socks5 node
    relay = relay_reality_node("relay-us", "185.222.43.186", 10031, base[0])
    res = residential_socks5_node("res-iproyal", "geo.iproyal.com", 12321, "user_sess", "pass123")
    nodes = base + [relay, res]

    parsed = yaml.safe_load(generate_local_clash_yaml(nodes, lang="zh"))
    groups = {g["name"]: g for g in parsed["proxy-groups"]}

    # Verify auto-test group ONLY contains datacenter nodes!
    auto_proxies = groups["⚡ 自动选择 (低延迟)"]["proxies"]
    assert "relay-us" not in auto_proxies
    assert "res-iproyal" not in auto_proxies
    assert "n-reality" in auto_proxies

    # Verify dedicated residential & relay group exists and contains them
    assert "🏠 住宅与家宽专线" in groups
    relay_proxies = groups["🏠 住宅与家宽专线"]["proxies"]
    assert "relay-us" in relay_proxies
    assert "res-iproyal" in relay_proxies

    # Verify AI & TikTok groups prioritize residential & relay
    assert groups["🤖 AI与ChatGPT"]["proxies"][0] == "🏠 住宅与家宽专线"
    assert groups["🛒 外贸与TikTok"]["proxies"][0] == "🏠 住宅与家宽专线"


def test_vmess_and_trojan_nodes():
    vm = vmess_ws_node("vm-node", "u-123", "1.2.3.4", 10022, "/ws", host="vps.com", tls=True)
    assert vm["uri"].startswith("vmess://")
    assert vm["clash"]["type"] == "vmess"
    assert vm["clash"]["tls"] is True

    tj = trojan_node("tj-node", "pass123", "1.2.3.4", 8443, sni="vps.com")
    assert tj["uri"].startswith("trojan://pass123@1.2.3.4:8443")
    assert tj["clash"]["type"] == "trojan"
    assert tj["clash"]["sni"] == "vps.com"

