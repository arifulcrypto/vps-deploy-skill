# Gemini / Google Antigravity Skill Guidelines (English)

The skill is auto-discovered from [`.agents/skills/vps-deployer/SKILL.md`](../.agents/skills/vps-deployer/SKILL.md) (a link to the root [`SKILL.md`](../SKILL.md), which is the source of truth).

## In-session protocol
1. Extract `ip`, SSH port/user/credentials, optional domain(s) and carrier from the conversation; ask for anything missing.
2. Choose the profile with the user (`reality-self` needs a DNS-only domain; otherwise `legacy`), write a config JSON, and run `python3 scripts/vps_deployer.py --config <file> --dry-run`. Show the plan and wait for confirmation.
3. Run the deployment with `run_command`. Do not run ad-hoc `sshpass`/`systemctl`/`pkill` commands against the server and do not edit the panel database yourself.
4. Opt-in flags (`--adopt-existing-panel`, `--stop-conflicting-services`, `--rotate-secrets`, `--online-sub`) only with explicit user consent.
5. On success, create a markdown artifact from `result.json` with the panel access, node links and embedded QR images (`![node](/absolute/path/qr_<node>.png)`), and note that it contains credentials. On failure, report the `[ERROR]` line and the SKILL.md troubleshooting entry.

Default output language is English (`en`).
