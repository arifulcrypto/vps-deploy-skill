"""Cloudflare record handling: only records this tool created may ever change."""
import pytest

from scripts.cloudflare_dns import MARKER, ensure_records, find_zone, planned_records, wait_for_dns
from scripts.remote import DeploymentError


class FakeAPI:
    def __init__(self, records=()):
        self.records = list(records)
        self.writes = []

    def __call__(self, token, method, path, body=None):
        if path.startswith("/zones?name="):
            return [{"id": "zone1"}] if path.endswith("=example.com") else []
        if method == "GET":
            return list(self.records)
        self.writes.append((method, path, body))
        return {}


def record(content="198.51.100.1", proxied=False, comment=None):
    return {"id": "r1", "content": content, "proxied": proxied, "comment": comment}


GRAY = [("A", "www.example.com", "198.51.100.1", False)]


def test_zone_is_found_from_a_subdomain():
    assert find_zone("t", "a.b.example.com", FakeAPI()) == "zone1"


def test_missing_zone_is_an_error():
    api = lambda *a, **k: []  # noqa: E731
    with pytest.raises(DeploymentError, match="No Cloudflare zone"):
        find_zone("t", "www.example.org", api)


def test_new_record_is_created_with_marker():
    api = FakeAPI()
    assert ensure_records("t", GRAY, api) == ["created www.example.com"]
    assert api.writes[0][0] == "POST" and api.writes[0][2]["comment"] == MARKER


def test_matching_record_is_left_alone():
    api = FakeAPI([record()])
    assert ensure_records("t", GRAY, api) == ["kept www.example.com"] and api.writes == []


def test_own_record_is_updated():
    api = FakeAPI([record(content="198.51.100.9", comment=MARKER)])
    ensure_records("t", GRAY, api)
    assert api.writes[0][0] == "PATCH"


def test_foreign_record_is_never_changed():
    api = FakeAPI([record(content="198.51.100.9")])
    with pytest.raises(DeploymentError, match="was not created by this tool"):
        ensure_records("t", GRAY, api)
    assert api.writes == []


def test_a_conflict_stops_before_any_write():
    class Mixed(FakeAPI):
        def __call__(self, token, method, path, body=None):
            if method == "GET" and "name=bad" in path:
                return [record(content="198.51.100.9")]
            if method == "GET" and "dns_records" in path:
                return []
            return super().__call__(token, method, path, body)

    api = Mixed()
    with pytest.raises(DeploymentError):
        ensure_records("t", GRAY + [("A", "bad.example.com", "198.51.100.1", True)], api)
    assert api.writes == []


def test_planned_records_follow_the_profile():
    base = {"domain": "www.example.com", "cdn_domain": None, "ipv6_domain": None, "ipv6": None,
            "panel_domain": None, "ip": "198.51.100.1"}
    assert planned_records(dict(base, profile="unified"))[0][3] is True
    assert planned_records(dict(base, profile="reality-self"))[0][3] is False


def test_wait_for_dns_stops_when_visible_and_gives_up_otherwise():
    assert wait_for_dns("x", "1.2.3.4", resolve=lambda n: ["1.2.3.4"])
    assert not wait_for_dns("x", "1.2.3.4", timeout=0, resolve=lambda n: [])
