---
name: vps-deployer
description: >-
  Deploys and maintains a 3X-UI proxy node on a Linux VPS over SSH. Profiles:
  `unified` (default, complete protocol matrix: Direct REALITY + Direct Hysteria 2 + Cloudflare CDN WS-TLS),
  `legacy` (alias to unified), and `reality-self` (single public TCP 443: VLESS-REALITY-Vision with own Nginx website).
  Provides public 0.0.0.0 panel access by default with optional SSH tunneling, automatic existing panel adoption,
  default online subscription URLs, owner-only reports, QR codes and local Clash/Mihomo YAML.
---

# VPS Deployer Skill

Source of truth for every agent adapter (`claude/`, `openai/`, `gemini/`). The engine is
`scripts/vps_deployer.py`; agents should call it instead of improvising remote commands.

## 1. What it does (and does not do)

- **Unified Protocol Matrix.** Deploys a complete suite of protocols:
  - **Direct REALITY (TCP + Vision)**: High performance, direct connection on high port (great for CN2/GIA/9929/CMIN2 optimized routes).
  - **Direct Hysteria 2 (UDP)**: High speed UDP port-hopping protocol with pinned certificate for bare-IP or domain.
  - **Cloudflare CDN (WS-TLS + 443)**: Resilient fallback through Cloudflare Anycast CDN with carrier clean IPs (when domain is set).
- **Public & Accessible by Default.** The 3X-UI panel listens on `0.0.0.0` by default with firewall port opened, giving operators immediate browser access (`http://<ip>:<port><path>`). SSH tunnel command is always provided as an alternative. Pass `--panel-private` to restrict to `127.0.0.1` loopback.
- **Instant Online Subscriptions.** Online subscription URLs (OnePage and Clash Verge Rev compatible) are produced by default (`--online-sub`) using high-availability CDN rule mirrors. Pass `--no-online-sub` for local YAML only.
- **Smooth Adoption.** Automatically adopts pre-existing 3X-UI panels and cleanly manages conflicting web servers by default. Only inbounds tagged `vps-skill-*` and client `vps-skill-<deploy_id>` are modified.
- **Agent Self-Healing.** Warning on minor verification/probe hiccups instead of crashing; ensures node links and reports are delivered.
- **Stable across re-runs.** UUID, passwords, REALITY keys, ports and paths are stored in `/etc/vps-skill/state.json` and reused. Explicit `--rotate-secrets` issues new credentials.

## 2. Profiles

| Profile | Description | Direct Protocols | CDN Protocols | Target Use Case |
| :--- | :--- | :--- | :--- | :--- |
| `unified` (default) / `legacy` | Complete protocol matrix in one subscription | VLESS-REALITY (Vision) + Hysteria 2 (UDP) | VLESS-WS-TLS on 443 + Carrier Clean IPs | BandwagonHost, RackNerd, Akile, VMISS, general VPS |
| `reality-self` | Port 443 stealth website fallback | VLESS-REALITY (Vision) on 443 -> own Nginx site | None (single 443) | Operators wanting single public 443 port disguised as personal site |

## 3. Inputs

Ask for what is missing; never invent credentials.

| Field | Required | Default | Notes |
| :--- | :--- | :--- | :--- |
| `ip` | **yes** | — | Public IPv4 |
| `ssh_pass` or `ssh_key` | **yes** | — | CLI argument `--ssh-pass` or env `VPS_SSH_PASS` |
| `ssh_port`, `ssh_user` | no | `22`, `root` | |
| `profile` | no | `unified` | `unified` (default), `legacy`, `reality-self` |
| `domain` | no | — | Required for `reality-self` or CDN nodes in `unified` |
| `ipv6`, `ipv6_domain` | no | — | Extra IPv6 CDN node (unified) |
| `panel_domain` | no | — | Makes the panel public over HTTPS with domain cert |
| `panel_private` | no | `false` | When true, restricts panel to 127.0.0.1 loopback |
| `enable_hy2` | no | `true` (unified) | `hy2_obfs` default on |
| `reality_sni` | no | `addons.mozilla.org` | External REALITY target (unified) |
| `panel_port`, `hy2_port`, `reality_port` | no | random high ports | Dynamic allocation with collision checks |
| `panel_user`, `panel_pass`, `node_pass` | no | generated | Passable via CLI `--panel-pass`, etc. |
| `adopt_existing_panel` | no | `true` | Adopts pre-installed 3X-UI |
| `stop_conflicting_services` | no | `true` | Stops conflicting web units on 80/443 |
| `online_sub` | no | `true` | Generates OnePage/Clash online subscription links |
| `output_dir`, `lang` | no | `./output/<ip>`, `en` | `lang`: `en` / `zh` |

## 4. Runbook for agents

1. **Collect & execute.** Gather VPS IP and root credentials. Call `scripts/vps_deployer.py`:
   ```bash
   python3 scripts/vps_deployer.py --ip <IP> --ssh-pass '<PASS>' [--domain <DOMAIN>]
   ```
2. **Review output.** The tool writes all artifacts to `./output/<ip>/`.
3. **Deliver.** Present:
   - Panel direct browser URL, user, password, and optional SSH tunnel command.
   - Node share links (VLESS Reality, Hysteria 2, CDN WS).
   - OnePage / Clash Verge Rev subscription URLs.
   - Clash configuration YAML file path.

## 5. Troubleshooting

| Error | Meaning | Action |
| :--- | :--- | :--- |
| `3X-UI is already installed but not managed by this skill` | Foreign panel found | Ask; re-run with `adopt_existing_panel` only if the user owns it |
| `Port conflicts detected ... TCP 80/443 is used by 'nginx'` | A web server owns a required port | Ask; `stop_conflicting_services` stops and disables only that unit. For `reality-self`, Nginx on 443 must be moved to `127.0.0.1:8443` manually |
| `certificate issuance failed` | ACME failed; no self-signed fallback | Check A/AAAA records, grey cloud for `reality-self`/`panel_domain`, port 80 reachable |
| `Inbound configuration failed: port conflict ... inbound #N` | A foreign inbound uses the planned port | Choose another `*_port` or remove that inbound yourself |
| `Expected listeners missing` | Xray rejected the configuration | See the journal excerpt; consider pinning `xui_version` |
| `Panel login verification failed` | Credentials did not work; nothing was reset | If 2FA is enabled, log in manually; otherwise check the panel |
| `Port 443 did not serve the deployed website` | REALITY → Nginx chain broken | Check `nginx -t`, `/etc/nginx/conf.d/vps-skill.conf`, and that 8443 is Nginx |

## 6. Files

```text
output/<ip>/                       (0700, every file 0600)
├── vps_<ip>_info.txt              report with links and terminal QR codes
├── result.json                    machine-readable result for agents
├── clash_config.yaml              local Clash/Mihomo config (route groups: direct / CDN / failover)
└── qr_<node>.png                  QR codes for the primary nodes
Server: /etc/vps-skill/state.json  (0600) deployment identity and secrets
        /etc/x-ui/x-ui.db.vps-skill-<ts>.bak  last five database backups
```
