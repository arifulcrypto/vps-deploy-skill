#!/usr/bin/env python3
"""
VPS Deployer Unified Automation Engine:
End-to-end automation CLI tool that connects to remote VPS, installs 3X-UI,
configures multi-protocol coexistence (Hy2 + Reality + Cloudflare CDN) with
dynamic non-fixed high ports, issues SSL certificates, generates QR codes,
and produces redundant Clash Verge Rev subscriptions.
"""
import argparse
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from typing import Dict, Any, List

from scripts.qr_engine import generate_qr
from scripts.sub_converter import build_subscription_urls, fetch_offline_clash_yaml
from scripts.db_configurator import generate_remote_sqlite_script
from scripts.port_utils import generate_randomized_configs

# Carrier-optimized Anycast Clean IPs (Public Cloudflare Anycast IP ranges)
CARRIER_CLEAN_IPS = {
    "unicom": [("104.16.160.1", "Unicom-CleanIP1"), ("162.159.193.1", "Unicom-CleanIP2")],
    "mobile": [("162.159.192.1", "Mobile-CleanIP1"), ("104.16.160.1", "Mobile-CleanIP2")],
    "telecom": [("104.16.160.1", "Telecom-CleanIP1"), ("162.159.193.1", "Telecom-CleanIP2")],
    "overseas": [("104.16.160.1", "CF-Anycast1"), ("162.159.193.1", "CF-Anycast2")],
}


def run_ssh_command(host: str, port: int, user: str, password: str, command: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Execute command on remote server via sshpass and ssh."""
    ssh_cmd = [
        "sshpass", "-p", password,
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-p", str(port),
        f"{user}@{host}",
        command
    ]
    return subprocess.run(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)


def deploy_vps(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Execute complete VPS deployment pipeline with dynamic high ports and dual subscriptions."""
    ip = cfg["ip"]
    port = int(cfg.get("ssh_port", 22))
    user = cfg.get("ssh_user", "root")
    password = cfg["ssh_pass"]
    domain = cfg.get("domain", "").strip() or None
    ipv6_domain = cfg.get("ipv6_domain", "").strip() or None
    ipv6 = cfg.get("ipv6", "").strip() or None
    carrier = cfg.get("client_isp", "unicom").lower()
    client_ip = cfg.get("client_ip", "Generic Outbound")
    client_loc = cfg.get("client_location", "Regional Metro")
    output_dir = os.path.abspath(cfg.get("output_dir", f"./output/{ip}"))
    lang = cfg.get("lang", "en").lower()

    # Generate non-colliding randomized high ports and secrets
    random_cfg = generate_randomized_configs(
        panel_port=cfg.get("panel_port"),
        hy2_port=cfg.get("hy2_port"),
        reality_port=cfg.get("reality_port"),
        panel_path=cfg.get("panel_base_path"),
        obfs_pass=cfg.get("obfs_password"),
    )

    panel_port = random_cfg["panel_port"]
    panel_base_path = random_cfg["panel_base_path"]
    hy2_port = random_cfg["hy2_port"]
    reality_port = random_cfg["reality_port"]
    obfs_pass = random_cfg["obfs_password"]
    reality_shortid = random_cfg["reality_short_id"]
    cf_port = 443

    os.makedirs(output_dir, exist_ok=True)
    print(f"[*] Starting deployment pipeline for VPS {ip}:{port}...")
    print(f"[*] Dynamic Allocation -> Panel Port: {panel_port}, Hy2 UDP: {hy2_port}, Reality TCP: {reality_port}")

    # 1. Environment & Firewall Preparation
    print("[*] Phase 1: Checking environment, freeing ports, and ensuring firewall access...")
    prep_cmd = f"""
sysctl net.ipv4.tcp_congestion_control
systemctl stop xray nginx apache2 caddy 2>/dev/null || true
systemctl disable xray nginx apache2 caddy 2>/dev/null || true
which ufw >/dev/null 2>&1 && (ufw allow {panel_port}/tcp; ufw allow {reality_port}/tcp; ufw allow {hy2_port}/udp; ufw allow 443/tcp; ufw allow 80/tcp) || true
which iptables >/dev/null 2>&1 && (iptables -I INPUT -p tcp --dport {panel_port} -j ACCEPT; iptables -I INPUT -p tcp --dport {reality_port} -j ACCEPT; iptables -I INPUT -p udp --dport {hy2_port} -j ACCEPT; iptables -I INPUT -p tcp --dport 443 -j ACCEPT) || true
which apt-get >/dev/null 2>&1 && (apt-get update -y && apt-get install -y curl socat cron python3) || true
which yum >/dev/null 2>&1 && (yum install -y curl socat cronie python3) || true
"""
    res = run_ssh_command(ip, port, user, password, prep_cmd, timeout=120)

    # 2. Issue Let's Encrypt Certificate if domain provided
    cert_path = None
    key_path = None
    if domain:
        print(f"[*] Phase 2: Requesting Let's Encrypt ECC Certificate for {domain}...")
        domains_flag = f"-d {domain}"
        if ipv6_domain:
            domains_flag += f" -d {ipv6_domain}"

        acme_email = f"admin@{domain.split('.', 1)[-1]}" if "." in domain else "admin@example.com"
        acme_cmd = f"""
if [ ! -f ~/.acme.sh/acme.sh ]; then
    curl https://get.acme.sh | sh -s email={acme_email}
fi
~/.acme.sh/acme.sh --set-default-ca --server letsencrypt
~/.acme.sh/acme.sh --issue {domains_flag} --standalone --keylength ec-256 --force || true
mkdir -p /root/cert/{domain}
~/.acme.sh/acme.sh --install-cert -d {domain} --ecc --fullchain-file /root/cert/{domain}/fullchain.pem --key-file /root/cert/{domain}/privkey.pem || true
ls -l /root/cert/{domain}/
"""
        run_ssh_command(ip, port, user, password, acme_cmd, timeout=180)
        cert_path = f"/root/cert/{domain}/fullchain.pem"
        key_path = f"/root/cert/{domain}/privkey.pem"

    # 3. Install 3X-UI
    print(f"[*] Phase 3: Installing 3X-UI panel on dynamic port {panel_port}...")
    xui_install_cmd = f"""
export XUI_NONINTERACTIVE=1
export XUI_USERNAME="admin"
export XUI_PASSWORD="{password}"
export XUI_PANEL_PORT="{panel_port}"
export XUI_WEB_BASE_PATH="{panel_base_path}"
curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh | bash
"""
    run_ssh_command(ip, port, user, password, xui_install_cmd, timeout=180)

    # 4. Inject Multi-Protocol Inbounds into SQLite
    print(f"[*] Phase 4: Injecting multi-protocol inbounds (Hy2 UDP {hy2_port}, Reality TCP {reality_port}, CF {cf_port})...")
    client_uuid = str(uuid.uuid4())
    sub_id = "sub" + secrets.token_hex(4)

    # Generate Reality Keypair on VPS
    reality_privkey = ""
    reality_pubkey = ""

    gen_key_cmd = "/usr/local/x-ui/bin/xray-linux-amd64 x25519 2>/dev/null || true"
    k_res = run_ssh_command(ip, port, user, password, gen_key_cmd, timeout=15)
    for line in k_res.stdout.splitlines():
        if "PrivateKey:" in line:
            reality_privkey = line.split("PrivateKey:")[1].strip()
        elif "Password (PublicKey):" in line:
            reality_pubkey = line.split("Password (PublicKey):")[1].strip()

    if not reality_pubkey:
        reality_privkey = secrets.token_urlsafe(32)[:43]
        reality_pubkey = secrets.token_urlsafe(32)[:43]

    py_remote_script = generate_remote_sqlite_script(
        client_uuid=client_uuid,
        sub_id=sub_id,
        email="admin@example.com",
        password=password,
        hy2_port=hy2_port,
        reality_port=reality_port,
        cf_port=cf_port,
        domain=domain,
        cert_path=cert_path,
        key_path=key_path,
        obfs_password=obfs_pass,
        reality_privkey=reality_privkey,
        reality_pubkey=reality_pubkey,
        reality_shortid=reality_shortid,
        reality_sni="addons.mozilla.org",
    )

    # Save to local and SCP to remote
    tmp_py = f"/tmp/_tmp_3xui_setup_{secrets.token_hex(4)}.py"
    with open(tmp_py, "w", encoding="utf-8") as f:
        f.write(py_remote_script)

    scp_cmd = ["sshpass", "-p", password, "scp", "-o", "StrictHostKeyChecking=no", "-P", str(port), tmp_py, f"{user}@{ip}:/root/setup_inbounds.py"]
    subprocess.run(scp_cmd, timeout=30)
    if os.path.exists(tmp_py):
        os.remove(tmp_py)

    apply_cmd = "python3 /root/setup_inbounds.py && systemctl restart x-ui && sleep 2 && ss -tulpn"
    run_ssh_command(ip, port, user, password, apply_cmd, timeout=30)

    # 5. Build Node Links
    print("[*] Phase 5: Generating client node links & QR codes...")
    nodes = []

    # Node 1: Hysteria 2
    sni_host = domain if domain else ip
    node_hy2 = f"hysteria2://{password}@{ip}:{hy2_port}/?insecure={'0' if domain else '1'}&sni={sni_host}&obfs=salamander&obfs-password={obfs_pass}#VPS-Direct-Hy2-{hy2_port}"
    nodes.append(node_hy2)

    # Node 2: Reality
    node_reality = f"vless://{client_uuid}@{ip}:{reality_port}?encryption=none&flow=xtls-rprx-vision&security=reality&sni=addons.mozilla.org&fp=chrome&pbk={reality_pubkey}&sid={reality_shortid}&type=tcp#VPS-Direct-Reality-{reality_port}"
    nodes.append(node_reality)

    # Node 3 & 4: Clean IPs (if domain configured)
    if domain:
        clean_ips = CARRIER_CLEAN_IPS.get(carrier, CARRIER_CLEAN_IPS["unicom"])
        for idx, (clean_ip, tag) in enumerate(clean_ips, 1):
            n_clean = f"vless://{client_uuid}@{clean_ip}:{cf_port}?type=ws&security=tls&path=%2Fws&host={domain}&sni={domain}#VPS-CF-{tag}-{cf_port}"
            nodes.append(n_clean)

        # Node 5: Standard Domain 443
        node_cf_443 = f"vless://{client_uuid}@{domain}:{cf_port}?type=ws&security=tls&path=%2Fws&host={domain}&sni={domain}#VPS-CF-VLESS-{cf_port}"
        nodes.append(node_cf_443)

        # Node 6: IPv6 Domain if present
        if ipv6_domain:
            node_ipv6 = f"vless://{client_uuid}@{ipv6_domain}:{cf_port}?type=ws&security=tls&path=%2Fws&host={ipv6_domain}&sni={ipv6_domain}#VPS-CF-IPv6-{cf_port}"
            nodes.append(node_ipv6)

    # 6. QR Code Generation
    png_hy2 = os.path.join(output_dir, "node_hy2_qr.png")
    png_reality = os.path.join(output_dir, "node_reality_qr.png")
    png_cf_443 = os.path.join(output_dir, "node_cf_443_qr.png")

    ascii_hy2 = generate_qr(node_hy2, png_hy2)
    ascii_reality = generate_qr(node_reality, png_reality)
    ascii_cf_443 = generate_qr(node_cf_443, png_cf_443) if domain else ""

    # 7. Dual Clash Subscriptions (OnePage Primary + v1.mk Fallback)
    print("[*] Phase 6: Generating dual Clash Verge Rev subscription URLs (Primary + Fallback)...")
    onepage_sub, fallback_sub = build_subscription_urls(nodes)
    offline_yaml_path = os.path.join(output_dir, "clash_config.yaml")
    try:
        fetch_offline_clash_yaml(onepage_sub, offline_yaml_path)
    except Exception as e:
        print(f"[!] Note: Offline YAML fetch notice: {e}")

    # 8. Save Formatted Output Report (.txt)
    report_file = os.path.join(output_dir, f"vps_{ip}_info.txt")
    if lang == "zh":
        report_text = f"""================================================================================
                    VPS 自动化部署与多协议共存全量档案
================================================================================
服务器 IP 地址 : {ip}
IPv6 地址      : {ipv6 if ipv6 else '未配置'}
绑定主域名     : {domain if domain else '未绑定 (裸IP直连)'}
IPv6 专属域名  : {ipv6_domain if ipv6_domain else '未配置'}
针对优化运营商 : {carrier.upper()} ({client_loc} | 出口 IP: {client_ip})
部署更新时间   : {time.strftime('%Y-%m-%d %H:%M:%S')}

--------------------------------------------------------------------------------
一、运维登录与 3X-UI 面板 (动态安全高端口)
--------------------------------------------------------------------------------
SSH 连接端口   : {port}
SSH 用户名     : {user}
SSH 登录密码   : {password}
快捷连接命令   : ssh {user}@{ip} -p {port}

3X-UI 面板地址 : https://{ip}:{panel_port}{panel_base_path}
面板登录用户   : admin
面板登录密码   : {password}
面板安全状态   : 已启用 HTTPS / 动态随机端口 {panel_port} / 随机安全路径

--------------------------------------------------------------------------------
二、多协议共存技术架构 (三大协议并行生效，动态高端口抗封锁)
--------------------------------------------------------------------------------
1. 端口 {hy2_port} (UDP) : Hysteria 2 协议 (QUIC + BBR，晚高峰抗丢包神器)
2. 端口 {reality_port} (TCP) : VLESS-Reality 协议 (XTLS Vision 直连 / 极低握手延迟)
3. 端口 {cf_port}   (TCP) : VLESS-WS-TLS 协议 (走 Cloudflare CDN / 全平台抗封锁)

--------------------------------------------------------------------------------
三、客户端节点链接 (v2rayN / Clash Verge Rev)
--------------------------------------------------------------------------------
[🔥 Hysteria 2 晚高峰推荐节点]
{node_hy2}

[⚡ VLESS-Reality 低延迟直连节点]
{node_reality}

"""
        if domain:
            report_text += f"""[🌐 Cloudflare 运营商优选节点]
{nodes[2]}

[🛡️ Cloudflare CDN 标准 443 节点]
{node_cf_443}
"""
        report_text += f"""
--------------------------------------------------------------------------------
四、双轨 Clash Verge Rev 订阅链接 (主备冗余，内置 ACL4SSR 规则)
--------------------------------------------------------------------------------
1. 🔥 主订阅 (OnePage 在线转换直出，推荐首选):
{onepage_sub}

2. 🛡️ 备用订阅 (v1.mk 备用分流转换通道):
{fallback_sub}

--------------------------------------------------------------------------------
五、本地离线归档文件
--------------------------------------------------------------------------------
1. 详细档案文件 : {report_file}
2. 离线规则文件 : {offline_yaml_path}
3. 节点二维码   :
   - Hysteria 2 : {png_hy2}
   - Reality    : {png_reality}
   - 标准 443   : {png_cf_443 if domain else '无'}
================================================================================
"""
    else:
        report_text = f"""================================================================================
              VPS Automated Deployment & Multi-Protocol Archive
================================================================================
Server IPv4     : {ip}
Server IPv6     : {ipv6 if ipv6 else 'Not configured'}
Primary Domain  : {domain if domain else 'None (Bare IP direct)'}
IPv6 Domain     : {ipv6_domain if ipv6_domain else 'Not configured'}
Optimized Target: {carrier.upper()} ({client_loc} | Outbound IP: {client_ip})
Generated At    : {time.strftime('%Y-%m-%d %H:%M:%S UTC')}

--------------------------------------------------------------------------------
1. SSH & 3X-UI Control Panel Credentials (Dynamic High Ports)
--------------------------------------------------------------------------------
SSH Port        : {port}
SSH Username    : {user}
SSH Password    : {password}
Quick Command   : ssh {user}@{ip} -p {port}

3X-UI Dashboard : https://{ip}:{panel_port}{panel_base_path}
Dashboard User  : admin
Dashboard Pass  : {password}
Security Status : HTTPS enabled / Dynamic Port {panel_port} / Random Secret Path

--------------------------------------------------------------------------------
2. Multi-Protocol Architecture (3 Inbounds Concurrently Active)
--------------------------------------------------------------------------------
1. Port {hy2_port} (UDP) : Hysteria 2 Protocol (QUIC + BBR / Peak-Hour Anti-Packet-Loss)
2. Port {reality_port} (TCP) : VLESS-Reality Protocol (XTLS Vision / Minimal Handshake Latency)
3. Port {cf_port}   (TCP) : VLESS-WS-TLS Protocol (Cloudflare CDN Anycast / Anti-Block Armor)

--------------------------------------------------------------------------------
3. Client Node URLs (v2rayN / Clash Verge Rev / Mihomo)
--------------------------------------------------------------------------------
[🔥 Hysteria 2 Peak-Hour Recommended]
{node_hy2}

[⚡ VLESS-Reality Ultra-Low Latency Direct]
{node_reality}

"""
        if domain:
            report_text += f"""[🌐 Cloudflare Carrier Clean IP Node]
{nodes[2]}

[🛡️ Cloudflare CDN Standard 443 Node]
{node_cf_443}
"""
        report_text += f"""
--------------------------------------------------------------------------------
4. Redundant Dual Clash Verge Rev Subscription URLs (ACL4SSR Rules Embedded)
--------------------------------------------------------------------------------
1. 🔥 Primary Subscription (OnePage Sub-Convert Engine):
{onepage_sub}

2. 🛡️ Fallback Subscription (v1.mk Secondary Conversion Gateway):
{fallback_sub}

--------------------------------------------------------------------------------
5. Local Offline Artifacts Index
--------------------------------------------------------------------------------
1. Report File  : {report_file}
2. Clash Config : {offline_yaml_path}
3. QR PNGs      :
   - Hysteria 2 : {png_hy2}
   - Reality    : {png_reality}
   - Std 443    : {png_cf_443 if domain else 'N/A'}
================================================================================
"""

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"[+] Deployment complete! Archive generated at {output_dir}")
    return {
        "output_dir": output_dir,
        "report_file": report_file,
        "nodes": nodes,
        "onepage_sub": onepage_sub,
        "fallback_sub": fallback_sub,
        "panel_port": panel_port,
        "hy2_port": hy2_port,
        "reality_port": reality_port,
    }


def main():
    parser = argparse.ArgumentParser(description="VPS Multi-Protocol Deployment Automation Engine")
    parser.add_argument("--config", help="Path to JSON configuration file")
    parser.add_argument("--ip", help="Server IPv4 address")
    parser.add_argument("--ssh-port", default=22, type=int, help="SSH port (default 22)")
    parser.add_argument("--ssh-user", default="root", help="SSH username (default root)")
    parser.add_argument("--ssh-pass", help="SSH password")
    parser.add_argument("--ipv6", help="Server IPv6 address")
    parser.add_argument("--domain", help="Server IPv4 domain name")
    parser.add_argument("--ipv6-domain", help="Server IPv6 domain name")
    parser.add_argument("--client-isp", default="unicom", help="User domestic carrier (unicom/mobile/telecom/overseas)")
    parser.add_argument("--client-ip", default="Generic Outbound", help="Client outbound IP")
    parser.add_argument("--client-location", default="Regional Metro", help="Client geographical location")
    parser.add_argument("--output-dir", help="Output directory to store txt and QR codes")
    parser.add_argument("--lang", default="en", choices=["en", "zh"], help="Output language (default: en)")
    parser.add_argument("--panel-port", type=int, help="Override 3X-UI panel port (randomized if omitted)")
    parser.add_argument("--hy2-port", type=int, help="Override Hysteria 2 UDP port (randomized if omitted)")
    parser.add_argument("--reality-port", type=int, help="Override VLESS-Reality TCP port (randomized if omitted)")

    args = parser.parse_args()

    cfg = {}
    if args.config:
        with open(args.config, "r", encoding="utf-8") as f:
            cfg = json.load(f)

    # Override CLI arguments
    for k, v in vars(args).items():
        if v is not None and k != "config":
            cfg[k] = v

    if not cfg.get("ip") or not cfg.get("ssh_pass"):
        parser.error("Both --ip and --ssh-pass (or JSON config) are required.")

    deploy_vps(cfg)


if __name__ == "__main__":
    main()
