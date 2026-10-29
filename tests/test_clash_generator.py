"""Local Clash configuration generator and node builder."""
import yaml

from scripts.clash_generator import generate_local_clash_yaml
from scripts.nodes import cdn_nodes, hy2_node, reality_node


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
