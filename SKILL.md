---
name: vps-deployer
description: >-
  Deploys and maintains a 3X-UI proxy node on a Linux VPS over SSH. Two profiles:
  `reality-self` (single public TCP 443: VLESS-REALITY-Vision whose target is the operator's own
  HTTPS website, so non-clients see a normal site) and `legacy` (REALITY on a random high port,
  optional Hysteria 2, VLESS-WS-TLS on 443 behind Cloudflare). Fails closed, keeps existing
  services/inbounds/2FA untouched, keeps the panel private, reuses stored secrets on re-runs, and
  writes owner-only reports, QR codes and a locally generated Clash/Mihomo YAML.
---

# VPS Deployer Skill

Source of truth for every agent adapter (`claude/`, `openai/`, `gemini/`). The engine is
`scripts/vps_deployer.py`; agents should call it instead of improvising remote commands.

## 1. What it does (and does not do)

- **Fails closed.** Report, links, QR codes and YAML are written only after every remote step,
  the listener check, the panel login probe and (for `reality-self`) the website check pass.
- **Non-destructive by default.** Existing web servers are never stopped unless the user asks
  (`stop_conflicting_services`). A 3X-UI not installed by this skill is not touched unless the user
  asks (`adopt_existing_panel`). Only inbounds tagged `vps-skill-*` and the client
  `vps-skill-<deploy_id>` are modified; foreign inbounds, clients, 2FA and panel TLS stay as they
  are. The database is backed up before each change and written in one transaction.
- **Stable across re-runs.** UUID, passwords, REALITY keys, ports and paths are stored on the server
  in `/etc/vps-skill/state.json` (0600) and reused, so client links stay valid and firewall rules do
  not accumulate. `rotate_secrets` issues new credentials explicitly.
- **Private management.** The panel (and 3X-UI's subscription server) listen on `127.0.0.1`;
  access is via SSH tunnel. A public HTTPS panel needs an explicit `panel_domain`.
- **Local client config.** `clash_config.yaml` is generated locally (`allow-lan: false`). Third-party
  converter URLs embed all credentials and are only produced with `online_sub`.
- **No guarantees about blocking.** Nothing here makes a server undetectable or unblockable.
  Choose a profile based on what actually works from the user's network.

## 2. Profiles

| | `reality-self` (recommended with a domain) | `legacy` (default) |
| :--- | :--- | :--- |
| Public TCP | 80 (ACME + redirect), 443 | REALITY high port; 80/443 when `domain` is set |
| Public UDP | Hysteria 2 only if `enable_hy2` | Hysteria 2 random high port (default on) |
| REALITY target | `127.0.0.1:8443` = own Nginx site, `xver: 1` | `reality_sni:443` (default `addons.mozilla.org`) |
| What a scanner sees on 443 | The operator's own website, valid cert for the domain | Xray WS-TLS behind Cloudflare |
| DNS | `domain` **DNS-only (grey cloud)** A record | `domain` Cloudflare-proxied (orange cloud) for WS |
| Certificate | acme.sh webroot via Nginx, reload Nginx on renewal | acme.sh standalone on :80, restart x-ui on renewal |

`reality-self` traffic flow:

```text
client ──TLS(SNI=domain)──▶ :443 Xray VLESS+REALITY+Vision ──valid client──▶ internet
                                  └─ anything else (PROXY v1) ─▶ 127.0.0.1:8443 Nginx ─▶ static site
:80 Nginx ─ /.well-known/acme-challenge/ ; everything else 301 → https
```

Known `legacy` limitation: REALITY forwards unauthenticated connections to the external target,
so scanners can use the port as a relay to that site, and a foreign certificate on a VPS IP is an
observable SNI/IP mismatch. `reality-self` avoids both.

## 3. Inputs

Ask for what is missing; never invent credentials. Before choosing `reality-self`, confirm the user
has a DNS-only hostname and that direct HTTPS to the VPS works from their network
(`curl -sv --resolve <domain>:443:<ip> https://<domain>/` once deployed, or any HTTPS test to the IP).

| Field | Required | Default | Notes |
| :--- | :--- | :--- | :--- |
| `ip` | **yes** | — | Public IPv4 |
| `ssh_pass` or `ssh_key` | **yes** | — | `ssh_pass` may also come from env `VPS_SSH_PASS` |
| `ssh_port`, `ssh_user` | no | `22`, `root` | |
| `ssh_known_hosts` | no | — | Pre-verified known_hosts file; otherwise trust-on-first-use (`accept-new`) |
| `profile` | no | `legacy` | `legacy` or `reality-self` |
| `domain` | `reality-self`: yes | — | See DNS row above |
| `ipv6`, `ipv6_domain` | no | — | `ipv6_domain` adds a CDN node (legacy) |
| `panel_domain` | no | — | Makes the panel public over HTTPS (added to the certificate) |
| `enable_hy2` | no | legacy on / reality-self off | `hy2_obfs` (Salamander) default on |
| `reality_sni` | no | `addons.mozilla.org` | legacy external target |
| `panel_port`, `hy2_port`, `reality_port` | no | random (45000-64000 / 30000-44999 / 20000-29999) | Checked against live listeners |
| `web_backend_port` | no | `8443` | reality-self loopback HTTPS |
| `panel_user`, `panel_pass`, `node_pass`, `obfs_password`, `panel_base_path` | no | generated | Secrets: 8-64 of `[A-Za-z0-9_-]` |
| `site_title`, `site_description` | no | derived | Website text (reality-self) |
| `node_prefix` | no | `srv` | Neutral node names, e.g. `srv-reality` |
| `client_isp` | no | `unicom` | `unicom`, `mobile`, `telecom`, `overseas` (CDN clean IPs) |
| `client_ip`, `client_location` | no | — | Report only |
| `acme_email`, `xui_version` | no | — | e.g. `xui_version: v3.11.0` pins the release |
| `adopt_existing_panel`, `stop_conflicting_services`, `rotate_secrets`, `reinstall_xui`, `online_sub` | no | `false` | Explicit opt-ins; confirm with the user first |
| `output_dir`, `lang` | no | `./output/<ip>`, `en` | `lang`: `en` / `zh` |

## 4. Runbook for agents

1. **Collect & confirm.** Gather inputs, choose a profile with the user, and run a dry run:
   `python3 scripts/vps_deployer.py --config <file> --dry-run`. Show the plan (ports, public
   firewall ports, certificate names) and get confirmation before the real run.
2. **Execute.** `python3 scripts/vps_deployer.py --config <file>` (or `python3 -m scripts.vps_deployer`).
   Phases: preflight (read-only) → packages/BBR/firewall → certificate (+ website) → 3X-UI →
   inbounds (conflict check, backup, transaction) → verification → local artifacts.
3. **On failure.** The process exits non-zero with `[ERROR] ...` and writes no artifacts. Report the
   message, explain it with section 5, and propose the matching opt-in only if it is appropriate.
   Never work around a failure by hand-editing the panel database or killing processes.
4. **Deliver.** Read `<output_dir>/result.json` and present: profile, panel access (SSH tunnel
   command, URL, user, password), node names and links, path of `clash_config.yaml` and QR PNGs,
   and the `notes`. Remind the user these files contain credentials.

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
