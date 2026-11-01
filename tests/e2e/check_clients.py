#!/usr/bin/env python3
"""
Send real traffic through every node of a generated Clash file with Mihomo.
`check_clients.py <clash_config.yaml> [server-ip]`: a server IP replaces hostnames, for test
domains without DNS, and turns off certificate checks for the private test CA.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import yaml

TARGET = "https://speed.cloudflare.com/__down?bytes=5000000"
MIHOMO = os.environ.get("MIHOMO", "mihomo")


def check(proxy, port):
    work = tempfile.mkdtemp()
    config = {"mixed-port": port, "mode": "global", "log-level": "error", "ipv6": False, "proxies": [proxy],
              "proxy-groups": [{"name": "GLOBAL", "type": "select", "proxies": [proxy["name"]]}], "rules": ["MATCH,GLOBAL"]}
    path = os.path.join(work, "c.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True)
    client = subprocess.Popen([MIHOMO, "-d", work, "-f", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(2)
        code = "000"
        for _ in range(3):
            code = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "30",
                                   "-x", f"http://127.0.0.1:{port}", TARGET], capture_output=True, text=True).stdout
            if code == "200":
                break
            time.sleep(2)
        return code
    finally:
        client.send_signal(signal.SIGTERM)
        client.wait()
        shutil.rmtree(work, ignore_errors=True)


def main():
    with open(sys.argv[1], encoding="utf-8") as f:
        proxies = yaml.safe_load(f)["proxies"]
    server = sys.argv[2] if len(sys.argv) > 2 else None
    failed = []
    for offset, proxy in enumerate(proxies):
        if server:
            proxy["server"] = server
            if "reality-opts" not in proxy:
                proxy["skip-cert-verify"] = True
        code = check(proxy, 17890 + offset)
        print(f"{proxy['name']:<16} {proxy['type']:<10} HTTP {code}")
        if code != "200":
            failed.append(proxy["name"])
    if failed:
        sys.exit(f"No traffic through: {', '.join(failed)}")


if __name__ == "__main__":
    main()
