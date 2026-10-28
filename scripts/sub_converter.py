#!/usr/bin/env python3
"""
Subscription Converter Engine: Generates online Clash Verge Rev
subscription URLs (via OnePage Sub-Convert) and downloads offline Clash YAML configurations.
"""
import urllib.parse
import urllib.request
import os
from typing import List, Tuple, Optional

DEFAULT_ACL4SSR_CONFIG = "https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/config/ACL4SSR_Online_Full_NoAuto.ini"
ONEPAGE_API_BASE = "https://onepage.czl.net/api/sub-convert"
FALLBACK_API_BASE = "https://api.v1.mk/sub"


def build_subscription_urls(nodes: List[str], config_url: str = DEFAULT_ACL4SSR_CONFIG) -> Tuple[str, str]:
    """
    Build primary OnePage and secondary fallback Clash subscription URLs.
    
    Args:
        nodes: List of raw node URLs (hysteria2://, vless://, etc.)
        config_url: Remote ACL4SSR rule configuration URL.
        
    Returns:
        Tuple of (onepage_sub_url, fallback_sub_url)
    """
    joined_nodes = "|".join(nodes)
    encoded_nodes = urllib.parse.quote(joined_nodes, safe="")
    encoded_config = urllib.parse.quote(config_url, safe="")

    onepage_url = f"{ONEPAGE_API_BASE}?target=clash&url={encoded_nodes}&config={encoded_config}"
    fallback_url = f"{FALLBACK_API_BASE}?target=clash&new_name=true&url={encoded_nodes}&config={encoded_config}"

    return onepage_url, fallback_url


def fetch_offline_clash_yaml(sub_url: str, output_yaml_path: Optional[str] = None, timeout: int = 15) -> str:
    """
    Fetch the converted Clash YAML configuration from subscription API and optionally save to disk.
    
    Args:
        sub_url: Complete subscription URL.
        output_yaml_path: Path to save the downloaded YAML file.
        timeout: HTTP request timeout in seconds.
        
    Returns:
        Downloaded YAML string content.
    """
    req = urllib.request.Request(
        sub_url,
        headers={"User-Agent": "ClashforWindows/0.20.39"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content = resp.read().decode("utf-8")

    if output_yaml_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_yaml_path)), exist_ok=True)
        with open(output_yaml_path, "w", encoding="utf-8") as f:
            f.write(content)

    return content


if __name__ == "__main__":
    sample_nodes = [
        "vless://00000000-0000-0000-0000-000000000001@1.2.3.4:443?type=ws&security=tls&path=%2Fws#SampleNode"
    ]
    p_url, f_url = build_subscription_urls(sample_nodes)
    print("OnePage URL:", p_url)
    print("Fallback URL:", f_url)
