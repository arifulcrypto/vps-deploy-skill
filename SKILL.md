---
name: vps-deployer
description: >-
  Autonomous multi-protocol VPS deployment and cluster manager skill.
  Deploys 3X-UI on dynamic randomized high ports, configures Hysteria 2 (dynamic high UDP with Salamander obfs),
  VLESS-Reality (dynamic high TCP with Vision), and VLESS-WS-TLS (Port 443 with Cloudflare Anycast CDN & Clean IPs).
  Issues Let's Encrypt ECC SAN certificates, generates terminal ASCII QR codes & high-res PNGs,
  downloads offline Clash configurations, and produces redundant OnePage & fallback Clash Verge Rev subscriptions.
---

# VPS Deployer & Multi-Protocol Cluster Manager Skill

## 1. Overview & Capabilities

The **VPS Deployer Skill** equips autonomous AI agents (OpenAI GPTs, Anthropic Claude, Google Gemini / Antigravity) and engineers with an end-to-end cognitive runbook and modular toolchain to provision overseas Linux servers into resilient, high-speed multi-protocol proxy nodes.

### Core Architectural Principles:
1. **Dynamic High Ports & Anti-Fingerprinting (No Fixed Ports)**:
   - **Hysteria 2**: Dynamically allocated random high UDP port (e.g. `30000-44999`), QUIC + BBR congestion control, random Salamander obfuscation password. Immune to TCP head-of-line blocking; handles 30%+ packet loss during peak hours.
   - **VLESS-Reality**: Dynamically allocated random high TCP port (e.g. `20000-29999`), XTLS Vision flow, Mozilla/legitimate SNI disguise. Bypasses port 443 active ISP probing with ultra-low 1-RTT handshake latency.
   - **3X-UI Dashboard**: Dynamically allocated random high TCP port (e.g. `45000-64000`) with a randomized secret URL base path (`/<secret_token>/`).
   - **VLESS-WS-TLS (Port 443)**: Standard HTTPS port required for Cloudflare CDN proxying, augmented by **Carrier Anycast Clean IPs** (optimized for China Unicom, China Mobile, and China Telecom).
2. **Dual-Domain SAN Let's Encrypt ECC Certificates**:
   - Automatically handles both IPv4 (`node.example.com`) and IPv6 (`ipv6.example.com`) domains using `acme.sh` standalone mode over port 80 (passes directly through Cloudflare orange cloud HTTP-01 passthrough).
3. **Dual Redundant Clash Subscriptions (Primary + Fallback)**:
   - **Primary**: OnePage Sub-Convert API (`https://onepage.czl.net/api/sub-convert?target=clash&url=...&config=...`) with embedded **ACL4SSR** rules (domestic apps/traffic routed DIRECT with zero proxy quota consumption).
   - **Fallback**: Secondary Subconverter API (`https://api.v1.mk/sub?target=clash&new_name=true&url=...&config=...`).
   - **Offline Backup**: Local `clash_config.yaml` downloaded directly into the archive folder for offline import.
4. **Agent Autonomy & Edge-Case Self-Healing**:
   - The agent does not simply run a blind monolithic script; it actively probes the environment, detects firewalls, cleans up conflicting web services, and handles schema variations dynamically.

---

## 2. Input Parameter Specification

When a user calls this skill, extract or prompt for the following fields (defaults apply where optional):

| Field Name | Type | Required | Default | Description | Example |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ip` | String | **Yes** | — | Public IPv4 address of the VPS | `198.51.100.1` |
| `ssh_port` | Integer | No | `22` | SSH port | `22` or `4400` |
| `ssh_user` | String | No | `root` | SSH username | `root` |
| `ssh_pass` | String | **Yes** | — | SSH password | `your_secure_password` |
| `domain` | String | No | `None` | IPv4 domain (Cloudflare Orange Cloud ON) | `node.yourdomain.com` |
| `ipv6` | String | No | `None` | Public IPv6 address | `2001:db8:85a3::1` |
| `ipv6_domain` | String | No | `None` | IPv6 domain (Cloudflare Orange Cloud ON) | `ipv6.yourdomain.com` |
| `client_isp` | String | No | `unicom` | User client carrier (`unicom`, `mobile`, `telecom`, `overseas`) | `unicom` |
| `client_ip` | String | No | `Generic`| User domestic outbound IP | `203.0.113.50` |
| `client_loc` | String | No | `Metro`  | User domestic geographical location | `East Asia Regional Metro` |
| `panel_port` | Integer | No | *Random*| 3X-UI web dashboard port | Random `45000-64000` |
| `hy2_port` | Integer | No | *Random*| Hysteria 2 UDP port | Random `30000-44999` |
| `reality_port`| Integer | No | *Random*| VLESS-Reality TCP port | Random `20000-29999` |
| `output_dir` | String | No | `./output/<ip>` | Local directory for reports and QR codes | `./output/198.51.100.1` |
| `lang` | String | No | `en` | Output language (`en` or `zh`) | `en` |

---

## 3. Agent Cognitive Decision Runbook & SOP

Follow this cognitive loop: **Inspect -> Adapt -> Execute -> Verify -> Archive**.

```
[Phase 1: Environment Inspection & Port/Firewall Adaptation]
       │
       ▼
[Phase 2: SSL Certificate Issuance & Validation]
       │
       ▼
[Phase 3: 3X-UI Non-Interactive Dynamic Deployment]
       │
       ▼
[Phase 4: SQLite Database Inbounds Injection]
       │
       ▼
[Phase 5: Port Probing & End-to-End WebSocket Verification]
       │
       ▼
[Phase 6: Artifact Archiving, QR Generation & Dual Clash Subscriptions]
```

### Phase 1: Environment Inspection & Port/Firewall Adaptation
1. **Test SSH connectivity**:
   `sshpass -p '<ssh_pass>' ssh -p <ssh_port> <ssh_user>@<ip> "uname -a && cat /etc/os-release"`
2. **Detect OS & Package Manager**:
   - If Debian/Ubuntu: `apt-get update && apt-get install -y curl socat cron python3`
   - If RHEL/CentOS/Rocky/AlmaLinux: `yum install -y curl socat cronie python3`
   - If Alpine: `apk add curl socat cronie python3`
3. **Verify & Enable BBR**:
   Inspect `sysctl net.ipv4.tcp_congestion_control`. If not `bbr`, append `net.core.default_qdisc=fq` and `net.ipv4.tcp_congestion_control=bbr` to `/etc/sysctl.conf` and reload `sysctl -p`.
4. **Clean Conflicting Services**:
   Detect if legacy web servers (e.g. default nginx, apache2, previous xray) occupy port 80 or 443:
   ```bash
   systemctl stop xray nginx apache2 caddy 2>/dev/null || true
   systemctl disable xray nginx apache2 caddy 2>/dev/null || true
   ```
5. **Dynamic Port Generation & Firewall Whitelisting**:
   Generate random high ports (`hy2_port`, `reality_port`, `panel_port`). Proactively open them on the remote host:
   ```bash
   which ufw >/dev/null 2>&1 && (ufw allow <panel_port>/tcp; ufw allow <reality_port>/tcp; ufw allow <hy2_port>/udp; ufw allow 443/tcp; ufw allow 80/tcp) || true
   which iptables >/dev/null 2>&1 && (iptables -I INPUT -p tcp --dport <panel_port> -j ACCEPT; iptables -I INPUT -p tcp --dport <reality_port> -j ACCEPT; iptables -I INPUT -p udp --dport <hy2_port> -j ACCEPT; iptables -I INPUT -p tcp --dport 443 -j ACCEPT) || true
   ```

### Phase 2: SSL Certificate Issuance (acme.sh Standalone)
If a domain is provided:
1. Ensure `acme.sh` is installed and set to Let's Encrypt:
   ```bash
   [ -f ~/.acme.sh/acme.sh ] || curl https://get.acme.sh | sh -s email=admin@example.com
   ~/.acme.sh/acme.sh --set-default-ca --server letsencrypt
   ```
2. Issue ECC certificate:
   - If both IPv4 and IPv6 domains exist, issue a **Multi-Domain SAN certificate**:
     `~/.acme.sh/acme.sh --issue -d <domain> -d <ipv6_domain> --standalone --keylength ec-256 --force`
   - If only IPv4 domain:
     `~/.acme.sh/acme.sh --issue -d <domain> --standalone --keylength ec-256 --force`
3. Install certificate:
   ```bash
   mkdir -p /root/cert/<domain>
   ~/.acme.sh/acme.sh --install-cert -d <domain> --ecc \
     --fullchain-file /root/cert/<domain>/fullchain.pem \
     --key-file /root/cert/<domain>/privkey.pem
   ```

### Phase 3: 3X-UI Non-Interactive Dynamic Installation
Deploy 3X-UI with the allocated random panel port and random secret URL base path:
```bash
export XUI_NONINTERACTIVE=1
export XUI_USERNAME="admin"
export XUI_PASSWORD="<ssh_pass>"
export XUI_PANEL_PORT="<panel_port>"
export XUI_WEB_BASE_PATH="<panel_base_path>"
curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh | bash
```

### Phase 4: Dynamic SQLite Inbounds Injection
Execute `scripts/db_configurator.py` remotely to configure `/etc/x-ui/x-ui.db`:
- Generates X25519 Reality keypair via `/usr/local/x-ui/bin/xray-linux-amd64 x25519`.
- Queries `PRAGMA table_info(inbounds)` to support schema variations (`exclude_from_sub`).
- Inbound 1: Port `443` (VLESS-WS-TLS), `wsSettings.headers = {}`.
- Inbound 2: Port `<hy2_port>` UDP (Hysteria 2), Salamander obfuscation, QUIC BBR.
- Inbound 3: Port `<reality_port>` TCP (VLESS-Reality), `xtls-rprx-vision`, SNI `addons.mozilla.org`.
- Restarts service: `systemctl restart x-ui`.

### Phase 5: Verification & End-to-End Handshake
1. **Port Checks**: `ss -tulpn` -> verify `<hy2_port>` (UDP), `<reality_port>` (TCP), `443` (TCP), `<panel_port>` (TCP).
2. **Cloudflare WebSocket Handshake**:
   ```bash
   curl -sS -v -H "Upgrade: websocket" -H "Connection: Upgrade" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" -H "Sec-WebSocket-Version: 13" https://<domain>/ws
   ```
   Expect: `HTTP/2 400 sec-websocket-version: 13 Bad Request` (confirms Xray WebSocket is live behind Cloudflare).
3. **Clean IP Test**:
   `curl -sS -v --resolve "<domain>:443:<clean_ip>" -H "Upgrade: websocket" ... https://<domain>/ws`

### Phase 6: Archiving, QR Generation & Dual Clash Subscriptions
1. Assemble node links (Hysteria 2, Reality, Carrier Clean IP 1 & 2, standard 443).
2. Run `scripts/qr_engine.py` to create high-resolution PNGs and terminal ASCII strings.
3. Run `scripts/sub_converter.py` to generate **dual Clash subscriptions** (OnePage primary + v1.mk fallback) and download `clash_config.yaml`.
4. Output structured report to user.

---

## 4. Troubleshooting & Self-Healing Decision Matrix

| Anomaly / Error | Root Cause | Agent Automated Resolution |
| :--- | :--- | :--- |
| `sqlite3.OperationalError: no column named exclude_from_sub` | 3X-UI version column discrepancy | Check `PRAGMA table_info(inbounds)`; dynamically construct `INSERT` query. |
| Connection timed out on domestic `curl --resolve "<domain>:443:<vps_ip>"` | Local ISP blocks naked overseas port 443 | Never route naked 443 direct. Use high ports (`<reality_port>`, `<hy2_port>`) for direct; Port 443 must transit Cloudflare CDN. |
| Cloudflare Error 526 on IPv6 domain | Origin VPS certificate lacks IPv6 domain in SAN | Issue dual-domain SAN certificate with `-d <v4_domain> -d <v6_domain>`. |
| `404 Not Found` on WebSocket `/ws` | Inbound `wsSettings.headers.Host` mismatch | Leave `headers: {}` empty in inbound `wsSettings` to accept any valid host header. |
| Port already in use | Random port collided with existing service | Run `ss -tulpn` to detect free port in range and bind to available port. |
| Random port blocked by VPS firewall | `ufw` or `iptables` active on new VPS | Proactively inject whitelist rules for allocated TCP and UDP ports during Phase 1. |
