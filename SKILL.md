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
  - **Opt-in compatibility inbounds**: `extra_protocols: ["vmess", "trojan"]` adds VMess-WS and Trojan-TLS for older clients. Xray marks WebSocket, VMess and Trojan as deprecated, so they stay off by default.
  - **Layer 4 Realm Relay Support**: Transparent passthrough relaying to US/home broadband NAT exits (`JP-Relay-US-Exit`).
  - **Commercial Residential / Sticky Proxy**: Support for SOCKS5 residential proxy pools (IPRoyal, IPCook, DataImpulse) with zero leak of user credentials.
- **Strict Clash Strategy Group Isolation.** Offline `clash_config.yaml` generation strictly isolates metered residential & home broadband relay nodes:
  - `⚡ 自动选择 (低延迟)`: Exclusively tests datacenter VPS nodes; residential nodes are strictly excluded to prevent traffic drainage and session drops.
  - `🏠 住宅与家宽专线`: Dedicated manual select group for residential/relay nodes with zero latency polling.
  - `🤖 AI与ChatGPT` & `🛒 外贸与TikTok`: Automatically prioritize `🏠 住宅与家宽专线`.
- **Public & Accessible by Default.** The 3X-UI panel listens on `0.0.0.0` by default with firewall port opened, giving operators immediate browser access (`http://<ip>:<port><path>`). SSH tunnel command is always provided as an alternative. Pass `--panel-private` to restrict to `127.0.0.1` loopback.

- **Instant Online Subscriptions.** Online subscription URLs (OnePage and Clash Verge Rev compatible) are produced by default (`--online-sub`) using high-availability CDN rule mirrors. Pass `--no-online-sub` for local YAML only.
- **Smooth Adoption.** Automatically adopts pre-existing 3X-UI panels and cleanly manages conflicting web servers by default. Only inbounds tagged `vps-skill-*` and client `vps-skill-<deploy_id>` are modified.
- **Agent Self-Healing.** Warning on minor verification/probe hiccups instead of crashing; ensures node links and reports are delivered.
- **Stable across re-runs.** UUID, passwords, REALITY keys, ports and paths are stored in `/etc/vps-skill/state.json` and reused. Explicit `--rotate-secrets` issues new credentials.

## 2. Profiles

| Profile | Description | Direct Protocols | CDN Protocols | Target Use Case |
| :--- | :--- | :--- | :--- | :--- |
| `unified` (default) / `legacy` | Complete protocol matrix in one subscription | VLESS-REALITY (Vision) + Hysteria 2 (UDP) | VLESS-WS-TLS on 443 + Carrier Clean IPs | BandwagonHost, RackNerd, Akile, VMISS, general VPS |
| `vision-tls` | One port with a real certificate, for clients without REALITY | VLESS + TLS + Vision -> own Nginx site | None |
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
| `panel_port`, `hy2_port` | no | random high ports | Dynamic allocation with collision checks on the final plan |
| `reality_port` | no | `443` when no domain needs it and it is free, otherwise a random high port | Existing deployments keep their port |
| `https_port` | no | `443` | Public HTTPS port. LXC secondary containers use their mapped port |
| `cdn_domain` | no | — | `reality-self` only: Cloudflare-proxied hostname on the same port as REALITY and the website |
| `cert_mode`, `cf_token` | no | `http-01` | `dns-01` issues through Cloudflare for hosts without public port 80. Token via `CF_TOKEN` |
| `extra_protocols`, `vmess_port`, `trojan_port` | no | none | `vmess`, `trojan`. Trojan needs `domain` |
| `relays` | no | `[]` | `[{"name","server","port"}]`: REALITY node through an L4 relay. Set up the relay itself separately |
| `residential` | no | `[]` | `[{"name","server","port","username","password"}]`: client-side SOCKS5 node. For server-side exit use `exit_proxy` |
| `enable_sub`, `sub_port` | no | `true`, `2096` | 3X-UI built-in subscription, published when the panel is public |
| `hy2_up`, `hy2_down` | no | unset (BBR) | Client Mbps. Setting both selects Brutal, so use real link speeds |
| `web_backend_port` | no | `8443` | Loopback website port for `reality-self` and `vision-tls` |
| `cdn_transport` | no | `both` for `reality-self`, otherwise `ws` | `ws`, `xhttp` or `both`. XHTTP uses `packet-up`, tested through real Cloudflare |
| `manage_dns` | no | `false` | Create or update the Cloudflare records. Needs `cf_token` with `Zone: DNS: Edit`. Records it did not create are never changed |
| `exit_proxy`, `exit_port` | no | none | `{"server","port","username","password","protocol"}`: adds a REALITY inbound whose traffic leaves the VPS through this SOCKS or HTTP proxy. Its node is treated as metered |
| `exit_all` | no | `false` | Send every inbound through `exit_proxy` and block QUIC. All nodes become metered |
| `hy2_masquerade` | no | `false` | `reality-self` with `hy2_obfs: false`: HTTP/3 visitors get the website |
| `panel_user`, `panel_pass`, `node_pass` | no | generated | Passable via CLI `--panel-pass`, etc. |
| `adopt_existing_panel` | no | `true` | Adopts pre-installed 3X-UI |
| `stop_conflicting_services` | no | `true` | Stops conflicting web units on 80/443 |
| `online_sub` | no | `true` | Generates OnePage/Clash online subscription links |
| `output_dir`, `lang` | no | `./output/<ip>`, `en` | `lang`: `en` / `zh` |
| `fail_closed` | no | `false` | Treat a failed panel login probe as a failed deployment |

With vps-lxc-skill, use `--from-lxc <result.json> --container <name>`, or pass that tool's `deploy_<name>.json` as `--config`. Explicit options override it.

Cloudflare notes, measured on a live deployment: use SSL mode Full (strict). `162.159.x.x` clean IPs answer on 443 only, so deployments on other HTTPS ports use the `104.x` and `172.67.x` addresses automatically. With `dns-01`, acme.sh keeps the token on the target for renewals, so give it DNS edit rights on one zone only.

Clients: use Mihomo **v1.19.9 or newer**. With an Xray server, Mihomo needs `support-x25519mlkem768: true`. The generated YAML, share links and panel subscription all set it, and older versions don't have the option. v1.19.9 and v1.19.33 are tested in CI. Tested versions and official downloads: [Software Versions](https://github.com/arifulcrypto/vps-lxc-skill/blob/main/docs/software-versions.md).

Host setup: see [Host Requirements](https://github.com/arifulcrypto/vps-lxc-skill/blob/main/docs/host-requirements.md) for the recommended OS, machine sizes and network settings.

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

## Reboot Rules

Reboots need no manual work. Every deployment installs a boot self-check.

After every boot, `vps-skill-bootcheck.timer` reapplies the firewall, starts `x-ui` and Nginx if needed, confirms every planned port is listening, and restarts `x-ui` once if ports stay missing. The result is written to `/var/lib/vps-skill/boot-status`.

**Rules for agents**

- After a reboot, wait 3 minutes, then read the status file.
- `OK` means finished. Do not restart anything.
- `FAILED` lists what stayed down. Read `/var/log/vps-skill-bootcheck.log`, fix that item, then run `systemctl start vps-skill-bootcheck.service`.
- Never reboot again as a first response.
- With vps-lxc-skill, also read `/var/lib/vps-lxc/boot-status` on the host. Containers must be up before this check can pass.
- With vps-lxc-skill, `upstream-down=` in the status means a relay or proxy exit outside this host didn't answer. Local services are fine, so check that provider.
- A deployment made before this feature gets the check on its next deployer run. Reruns keep links and ports.

## Residential and Relay Exits

Choose by what you need the exit to do.

| Pattern | Set up with | Traffic path | Use when |
| :--- | :--- | :--- | :--- |
| Whole node through a proxy | `exit_proxy` + `exit_all: true` | Client -> VPS -> residential proxy -> site | One container should always look residential |
| One extra node through a proxy | `exit_proxy` + `exit_port` | As above, for that node only | You want normal and residential nodes on one server |
| Layer 4 relay | Realm, then `relays` | Client -> VPS -> your own exit server -> site | You own a server elsewhere |

- **Sticky sessions:** commercial pools often take session settings in the username. DataImpulse uses `USER__cr.us;sessid.NAME;sessttl.1440` for the same IP for up to 24 hours. Connections drop when the session ends, and clients reconnect with a new IP automatically. Check your provider's syntax.
- **TCP only:** many such proxies don't carry UDP, so `exit_all` blocks QUIC on port 443. Apps fall back to TCP through the proxy, and traffic can't leak out through the VPS address.
- **Metered traffic:** residential nodes are never in automatic latency testing. Keep it that way, because probes use paid traffic.
- **Check the real exit:** run a client, open `https://www.cloudflare.com/cdn-cgi/trace`, and look up the IP. A provider calling a line "residential" doesn't prove it.
- **Combine servers:** merge per-server files into one client config, with metered nodes kept out of automatic groups:

```bash
python3 scripts/merge_clash.py --output cluster.yaml c1.yaml:direct c2.yaml:residential c3.yaml:relay
```

## Xray Compatibility & Client Group Ordering

### 1. Xray Core Version Pinning for Mihomo / Clash Verge Rev
- **Upstream Change**: Starting with Xray-core `v26.7.11`, upstream altered REALITY handshake/AEAD verification logic. Clients using Mihomo (Clash Meta / Clash Verge Rev) fail REALITY authentication (`REALITY Authentication: false`) against newer Xray cores.
- **Universal Stable Release**: Deploy Xray-core `v26.6.27`. It fully supports the modern 3X-UI `tunnel` Inbound while maintaining 100% cryptographic compatibility with Mihomo and v2rayN.
- **Vision Flow Override**: In 3X-UI deployments, `client_inbounds.flow_override` must be populated with `xtls-rprx-vision`. If empty, Xray omits client flow on restart, causing v2rayN to fail with `-1`.

### 2. Dual-Exit & Fallback Architecture
When relaying traffic to an external landing node (e.g. US ISP NAT via Realm):
- Generate both the relayed link (`vless://...@RELAY_IP:RELAY_PORT...`) and the direct landing link (`vless://...@LANDING_IP:LANDING_PORT...`) as an unrelayed fallback.
- Both endpoints should be documented in `vless_node.txt`, Base64 subscriptions, and Clash YAML.

### 3. Clash Verge Rev UI Placement & Neutral Naming
- In `proxy-groups:`, place `🚀 节点选择` at index 0 so it appears as the primary card in the Clash Verge Rev UI.
- Set `⚡ 自动选择 (低延迟)` as the first option within `🚀 节点选择`.
- Ensure acyclic group graphs without circular back-references from child groups (`AI与ChatGPT`, `外贸与TikTok`) to `🚀 节点选择`.
- Enforce neutral naming conventions without sensitive ISP/carrier names in client profiles.
