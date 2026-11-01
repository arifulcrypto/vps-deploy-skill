#!/usr/bin/env python3
"""Ask real Mihomo to load every node mix. `mihomo -t` rejects group cycles that unit tests could miss."""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from scripts.clash_generator import generate_local_clash_yaml  # noqa: E402
from scripts.nodes import (cdn_nodes, hy2_node, reality_node, relay_reality_node,  # noqa: E402
                           residential_socks5_node, trojan_node, vision_tls_node, vmess_ws_node, xhttp_nodes)

UUID = "11111111-1111-1111-1111-111111111111"
PUBLIC_KEY = "Z84J2IelR9ch3k8VtlVhhs5ycBUlXA7wHBWcBrjqnAw"
direct = [reality_node("n", UUID, "198.51.100.1", 443, "www.example.com", PUBLIC_KEY, "ab12"),
          hy2_node("n", "pw", "198.51.100.1", 31000, sni="www.example.com", obfs_password="ob"),
          vmess_ws_node("n-vmess", UUID, "198.51.100.1", 11000, "/v"),
          trojan_node("n-trojan", "pw", "198.51.100.1", 12000, sni="www.example.com")]
cdn = (cdn_nodes("n", UUID, "cdn.example.com", "/ws", [("162.159.193.1", "a")])
       + xhttp_nodes("n", UUID, "cdn.example.com", "/x", [("162.159.193.1", "a")])
       + [vision_tls_node("n", UUID, "www.example.com", 443)])
relay = [relay_reality_node("relay-a", "198.51.100.2", 10031, direct[0])]
residential = [residential_socks5_node("res-a", "203.0.113.5", 12321, "user", "pass")]
MIXES = {"direct": direct, "direct+cdn": direct + cdn, "mixed": direct + cdn + relay + residential,
         "relay-only": relay, "residential-only": residential, "relay+residential": relay + residential}

work = tempfile.mkdtemp()
for lang in ("en", "zh"):
    for label, nodes in MIXES.items():
        path = os.path.join(work, f"{label}-{lang}.yaml")
        generate_local_clash_yaml(nodes, path, lang=lang)
        res = subprocess.run([os.environ.get("MIHOMO", "mihomo"), "-t", "-d", work, "-f", path],
                             capture_output=True, text=True)
        print(f"{label:<20} {lang} rc={res.returncode}")
        if res.returncode != 0:
            sys.exit(res.stdout[-800:] + res.stderr[-800:])
