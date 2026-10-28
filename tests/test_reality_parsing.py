"""Test Reality key output parsing logic across Xray binary versions and architectures."""
import re


def parse_reality_keys(stdout_text: str):
    m_priv = re.search(r"Private\s*Key\s*:\s*(\S+)", stdout_text, re.IGNORECASE)
    m_pub = re.search(r"(?:Public\s*Key|Password\s*\(PublicKey\))\s*:\s*(\S+)", stdout_text, re.IGNORECASE)
    reality_privkey = m_priv.group(1).strip() if m_priv else ""
    reality_pubkey = m_pub.group(1).strip() if m_pub else ""
    return reality_privkey, reality_pubkey


def test_reality_key_parsing_legacy_amd64():
    sample = """
PrivateKey: uL6w...priv...key=
Password (PublicKey): aB8x...pub...key=
"""
    priv, pub = parse_reality_keys(sample)
    assert priv == "uL6w...priv...key="
    assert pub == "aB8x...pub...key="


def test_reality_key_parsing_modern_arm64():
    sample = """
Private key: uL6w...priv...key=
Public key: aB8x...pub...key=
"""
    priv, pub = parse_reality_keys(sample)
    assert priv == "uL6w...priv...key="
    assert pub == "aB8x...pub...key="


def test_reality_key_parsing_mixed_case():
    sample = """
Private Key: myprivkey123
Public Key: mypubkey456
"""
    priv, pub = parse_reality_keys(sample)
    assert priv == "myprivkey123"
    assert pub == "mypubkey456"


def test_reality_key_parsing_failure():
    sample = "command not found: xray"
    priv, pub = parse_reality_keys(sample)
    assert priv == ""
    assert pub == ""
