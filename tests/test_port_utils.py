"""Port selection and secret generators."""
import pytest

from scripts import port_utils
from scripts.port_utils import (PORT_RANGES, UNAMBIGUOUS_CHARSET, generate_unambiguous_password,
                                normalize_base_path, random_path, random_port)


def test_charset_excludes_ambiguous_characters():
    for ch in "0Oo1lI":
        assert ch not in UNAMBIGUOUS_CHARSET


def test_password_uses_only_the_charset(monkeypatch):
    pw = generate_unambiguous_password(16, prefix="Admin_")
    assert pw.startswith("Admin_") and len(pw) == 22
    assert set(pw[6:]) <= set(UNAMBIGUOUS_CHARSET)


def test_random_port_respects_range_avoid_and_in_use(monkeypatch):
    low, high = PORT_RANGES["reality"]
    seq = iter([low, low + 1, low + 2])
    monkeypatch.setattr(port_utils._rng, "randint", lambda a, b: next(seq))
    assert random_port("reality", avoid={low}, in_use=lambda p: p == low + 1) == low + 2


def test_random_port_gives_up_when_exhausted(monkeypatch):
    monkeypatch.setattr(port_utils._rng, "randint", lambda a, b: a)
    with pytest.raises(RuntimeError):
        random_port("hy2", avoid={PORT_RANGES["hy2"][0]}, attempts=5)


def test_paths():
    assert random_path().startswith("/") and random_path().endswith("/")
    assert normalize_base_path("abc") == "/abc/"
