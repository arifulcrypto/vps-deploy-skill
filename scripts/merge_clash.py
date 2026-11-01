#!/usr/bin/env python3
"""
Merge Clash files from several servers into one client config.
Each input gets a route, so metered exits stay out of automatic latency testing:
  python3 scripts/merge_clash.py --output cluster.yaml c1.yaml:direct c2.yaml:residential c3.yaml:relay
"""
import argparse
import os
import sys
from typing import Any, Dict, List, Tuple

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.clash_generator import generate_local_clash_yaml  # noqa: E402

ROUTES = ("direct", "cdn", "relay", "residential")


def collect(inputs: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    seen = set()
    for path, route in inputs:
        if route not in ROUTES:
            raise ValueError(f"unknown route '{route}'. Choose one of: {', '.join(ROUTES)}")
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        proxies = data.get("proxies", []) if isinstance(data, dict) else data
        for proxy in proxies:
            if proxy["name"] in seen:
                raise ValueError(f"duplicate node name: {proxy['name']}")
            seen.add(proxy["name"])
            nodes.append({"clash": proxy, "route": route})
    return nodes


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lang", choices=["en", "zh"], default="en")
    parser.add_argument("inputs", nargs="+", help="FILE:ROUTE, where ROUTE is direct, cdn, relay or residential")
    args = parser.parse_args(argv)
    pairs = [tuple(item.rsplit(":", 1)) if ":" in item else (item, "direct") for item in args.inputs]
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(generate_local_clash_yaml(collect(pairs), lang=args.lang))


if __name__ == "__main__":
    main()
