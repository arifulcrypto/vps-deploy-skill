#!/usr/bin/env python3
"""
Cloudflare DNS records for a deployment.
Creates or updates A/AAAA records through the API, using a token limited to
`Zone: DNS: Edit`. Records this tool creates carry a marker comment, and any other
record is never changed: a conflict stops the deployment instead.
"""
import http.client
import json
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from scripts.remote import DeploymentError

API = "https://api.cloudflare.com/client/v4"
MARKER = "managed by vps-deploy-skill"
CONNECT_TIMEOUT = 5


def _connect_first_working(host: str, port: int, read_timeout: float) -> socket.socket:
    """IPv4 first, with a short connect timeout: broken IPv6 must not stall every API call."""
    addresses = sorted(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM), key=lambda a: a[0] != socket.AF_INET)
    error: Optional[OSError] = None
    for family, kind, proto, _, address in addresses:
        sock = socket.socket(family, kind, proto)
        sock.settimeout(CONNECT_TIMEOUT)
        try:
            sock.connect(address)
            sock.settimeout(read_timeout)
            return sock
        except OSError as e:
            error = e
            sock.close()
    raise error or OSError(f"no addresses for {host}")


class _Connection(http.client.HTTPSConnection):
    def connect(self):
        sock = _connect_first_working(self.host, self.port, self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)


class _Handler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_Connection, req)


_opener = urllib.request.build_opener(_Handler)


def _call(token: str, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with _opener.open(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as e:
        try:
            payload = json.load(e)
        except ValueError:
            raise DeploymentError(f"Cloudflare API error: HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise DeploymentError(f"Cloudflare API is unreachable: {e}")
    if not payload.get("success"):
        messages = "; ".join(e.get("message", "") for e in payload.get("errors", []))
        raise DeploymentError(f"Cloudflare API rejected the request: {messages}")
    return payload.get("result")


def find_zone(token: str, hostname: str, call: Callable = _call) -> str:
    labels = hostname.split(".")
    for i in range(len(labels) - 1):
        name = ".".join(labels[i:])
        zones = call(token, "GET", f"/zones?name={urllib.parse.quote(name)}")
        if zones:
            return zones[0]["id"]
    raise DeploymentError(f"No Cloudflare zone for {hostname} is visible to this token.")


def planned_records(c: Dict[str, Any]) -> List[Tuple[str, str, str, bool]]:
    """(type, name, content, proxied) for every hostname of the deployment."""
    records: List[Tuple[str, str, str, bool]] = []
    if c["domain"]:
        records.append(("A", c["domain"], c["ip"], c["profile"] != "reality-self"))
    if c["cdn_domain"]:
        records.append(("A", c["cdn_domain"], c["ip"], True))
    if c["ipv6_domain"] and c["ipv6"]:
        records.append(("AAAA", c["ipv6_domain"], c["ipv6"], True))
    if c["panel_domain"]:
        records.append(("A", c["panel_domain"], c["ip"], False))
    return records


def ensure_records(token: str, records: List[Tuple[str, str, str, bool]], call: Callable = _call) -> List[str]:
    """Make the records match. Everything is checked before the first write."""
    changes: List[Tuple[str, str, Dict[str, Any]]] = []
    done = []
    for rtype, name, content, proxied in records:
        zone = find_zone(token, name, call)
        path = f"/zones/{zone}/dns_records"
        existing = call(token, "GET", f"{path}?type={rtype}&name={urllib.parse.quote(name)}") or []
        body = {"type": rtype, "name": name, "content": content, "proxied": proxied, "ttl": 1, "comment": MARKER}
        if not existing:
            changes.append(("POST", path, body))
            done.append(f"created {name}")
            continue
        record = existing[0]
        if len(existing) > 1:
            raise DeploymentError(f"{name} has several {rtype} records; fix them in Cloudflare first.")
        if record.get("content") == content and bool(record.get("proxied")) == proxied:
            done.append(f"kept {name}")
        elif record.get("comment") == MARKER:
            changes.append(("PATCH", f"{path}/{record['id']}", body))
            done.append(f"updated {name}")
        else:
            raise DeploymentError(f"{name} already points elsewhere and was not created by this tool: "
                                  f"{record.get('content')}, proxied={record.get('proxied')}. Change it yourself "
                                  "or use another hostname.")
    for method, path, body in changes:
        call(token, method, path, body)
    return done


def wait_for_dns(name: str, expected: str, timeout: int = 90, resolve: Optional[Callable] = None,
                 sleep: Callable = time.sleep) -> bool:
    """Wait until a DNS-only record is visible on a public resolver."""
    resolve = resolve or _doh_lookup
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if expected in resolve(name):
            return True
        sleep(3)
    return False


def _doh_lookup(name: str) -> List[str]:
    request = urllib.request.Request(f"https://1.1.1.1/dns-query?name={urllib.parse.quote(name)}&type=A",
                                     headers={"Accept": "application/dns-json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return [a.get("data", "") for a in json.load(response).get("Answer", [])]
    except (urllib.error.URLError, TimeoutError, ValueError):
        return []
