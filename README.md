

## Reboot Rules

Reboots need no manual work. Every deployment installs a boot self-check.

After every boot, `vps-skill-bootcheck.timer` reapplies the firewall, starts `x-ui` and Nginx if needed, confirms every planned port is listening, and restarts `x-ui` once if ports stay missing. The result is written to `/var/lib/vps-skill/boot-status`.

**Rules for agents**

- After a reboot, wait 3 minutes, then read the status file.
- `OK` means finished. Do not restart anything.
- `FAILED` lists what stayed down. Read `/var/log/vps-skill-bootcheck.log`, fix that item, then run `systemctl start vps-skill-bootcheck.service`.
- Never reboot again as a first response.
- With vps-lxc-skill, also read `/var/lib/vps-lxc/boot-status` on the host. Containers must be up before this check can pass.
- A deployment made before this feature gets the check on its next deployer run. Reruns keep links and ports.
