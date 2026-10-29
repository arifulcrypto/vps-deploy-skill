"""Test port randomizer and unambiguous password generator."""
from scripts.port_utils import generate_randomized_configs, generate_unambiguous_password


def test_randomized_ports_range():
    cfg = generate_randomized_configs()
    assert 45000 <= cfg["panel_port"] <= 64000
    assert 30000 <= cfg["hy2_port"] <= 44999
    assert 20000 <= cfg["reality_port"] <= 29999
    assert cfg["panel_port"] != cfg["hy2_port"]
    assert cfg["panel_port"] != cfg["reality_port"]
    assert cfg["hy2_port"] != cfg["reality_port"]
    assert cfg["panel_base_path"].startswith("/") and cfg["panel_base_path"].endswith("/")


def test_unambiguous_password_generation():
    pw = generate_unambiguous_password(16, prefix="Admin_")
    assert pw.startswith("Admin_")
    assert len(pw) == 6 + 16
    # Verify no ambiguous characters (0, O, o, 1, l, I) exist
    for char in ["0", "O", "o", "1", "l", "I"]:
        assert char not in pw[6:]
