#!/usr/bin/env python3
"""
Port and Secret Utilities:
Random high-port selection that avoids ports already planned or in use, and
generators for passwords, paths and identifiers.
"""
import secrets
from typing import Callable, Dict, Iterable, Tuple

# Unambiguous charset: excludes 0/O/o and 1/l/I.
UNAMBIGUOUS_CHARSET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz"

PORT_RANGES: Dict[str, Tuple[int, int]] = {
    "panel": (45000, 64000),
    "hy2": (30000, 44999),
    "reality": (20000, 29999),
}

# Cloudflare officially supported secondary HTTPS ports (ideal for admin panels under CDN proxy)
CLOUDFLARE_HTTPS_PORTS = (2087, 2053, 2083, 8443)

_rng = secrets.SystemRandom()


def generate_unambiguous_password(length: int = 16, prefix: str = "") -> str:
    """High-entropy password that survives manual transcription and is URL-safe."""
    return prefix + "".join(secrets.choice(UNAMBIGUOUS_CHARSET) for _ in range(length))


def random_port(kind: str, avoid: Iterable[int] = (), in_use: Callable[[int], bool] = lambda p: False,
                attempts: int = 200) -> int:
    """Pick a random port from the range for `kind` that is neither in `avoid` nor `in_use`."""
    low, high = PORT_RANGES[kind]
    avoid = set(avoid)
    for _ in range(attempts):
        port = _rng.randint(low, high)
        if port not in avoid and not in_use(port):
            return port
    raise RuntimeError(f"no free {kind} port found in {low}-{high}")


def random_path(nbytes: int = 12) -> str:
    """Random URL path segment of URL-safe characters, e.g. '/Xy3_k-.../'."""
    return f"/{secrets.token_urlsafe(nbytes)}/"


def normalize_base_path(path: str) -> str:
    path = path if path.startswith("/") else f"/{path}"
    return path if path.endswith("/") else f"{path}/"
