# Gemini / Google Antigravity Skill Guidelines (English)

This document defines the operational runbook when activating the `vps-deployer` skill inside the **Google Antigravity** environment or via the Gemini CLI.

## In-Session Execution Protocol
1. **Interactive Extraction**:
   When the user supplies credentials informally, dynamically extract:
   - Host IP & Port
   - Password
   - Cloudflare-proxied domain (optional)
   - Domestic outbound IP and carrier (Unicom / Mobile / Telecom)
2. **Dynamic Non-Fixed Ports**:
   - Randomize high UDP port for Hysteria 2 (`30000-44999`).
   - Randomize high TCP port for VLESS-Reality (`20000-29999`).
   - Randomize high TCP port for 3X-UI web dashboard (`45000-64000`) and randomize base path.
   - Whitelist the selected ports via remote firewall rules automatically.
3. **Autonomous Tool Invocations**:
   - Proactively probe the environment for port conflicts and legacy web servers.
   - Use `run_command` with `sshpass` to execute commands on the remote VPS.
   - Run `python3 scripts/vps_deployer.py` directly to handle end-to-end tasks.
4. **Artifact Generation & Dual Subscriptions**:
   - Create a dedicated markdown artifact in the session artifact directory (`<appDataDir>/brain/<conversation-id>/`) embedding generated QR code PNG images with `![alt](/absolute/path)`.
   - Embed file links using markdown link syntax `[file.txt](file:///absolute/path)`.
   - Output both Primary (OnePage) and Fallback (v1.mk) Clash Verge Rev subscription links.
   - Default output language is English (`en`).
