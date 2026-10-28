#!/usr/bin/env python3
"""
Port and Secret Utilities:
Generates randomized high ports and secrets to prevent fingerprinting
and avoid fixed port blocking.
"""
import secrets
import random
from typing import Dict, Any


def generate_randomized_configs(
    panel_port: int = None,
    hy2_port: int = None,
    reality_port: int = None,
    panel_path: str = None,
    obfs_pass: str = None,
) -> Dict[str, Any]:
    """
    Generate randomized, non-colliding high ports and secret tokens.
    """
    # Random high ports
    selected_panel_port = panel_port or random.randint(45000, 64000)
    
    # Ensure Hysteria 2 and Reality ports are distinct
    selected_hy2_port = hy2_port or random.randint(30000, 44999)
    selected_reality_port = reality_port or random.randint(20000, 29999)

    # Random secret URL path for 3X-UI panel
    selected_panel_path = panel_path or f"/{secrets.token_urlsafe(12)}/"
    if not selected_panel_path.startswith("/"):
        selected_panel_path = f"/{selected_panel_path}"
    if not selected_panel_path.endswith("/"):
        selected_panel_path = f"{selected_panel_path}/"

    # Random salamander obfuscation password
    selected_obfs = obfs_pass or secrets.token_hex(8)

    # Random reality shortId
    reality_short_id = secrets.token_hex(4)

    return {
        "panel_port": selected_panel_port,
        "hy2_port": selected_hy2_port,
        "reality_port": selected_reality_port,
        "panel_base_path": selected_panel_path,
        "obfs_password": selected_obfs,
        "reality_short_id": reality_short_id,
    }


if __name__ == "__main__":
    cfg = generate_randomized_configs()
    print("Randomized configuration sample:")
    print(cfg)
