#!/usr/bin/env python3
"""
Boot self-check for a deployment:
A systemd timer runs one static script after every boot. It reapplies the firewall, starts the
deployment's services, confirms every planned port is listening, and restarts the panel once
if ports are still missing. The result goes to a status file, so a reboot needs no manual work.
"""
from typing import Dict, List, Sequence

from scripts import web_profile

CONFIG = "/etc/vps-skill/boot-check.conf"
FIREWALL = "/etc/vps-skill/firewall.sh"
SCRIPT = "/usr/local/sbin/vps-skill-bootcheck"
STATUS = "/var/lib/vps-skill/boot-status"
LOG = "/var/log/vps-skill-bootcheck.log"
SERVICE = "/etc/systemd/system/vps-skill-bootcheck.service"
TIMER = "/etc/systemd/system/vps-skill-bootcheck.timer"

CHECK_SCRIPT = r"""#!/bin/bash
# Installed by vps-deploy-skill. Runs after every boot through vps-skill-bootcheck.timer.
export PATH="$PATH:/usr/sbin:/sbin"
CONFIG=/etc/vps-skill/boot-check.conf
FIREWALL=/etc/vps-skill/firewall.sh
STATUS=/var/lib/vps-skill/boot-status
ATTEMPTS="${BOOTCHECK_ATTEMPTS:-12}"
WAIT="${BOOTCHECK_WAIT:-10}"
HEAL_AT=4

log() { echo "$(date -Is) $*" | tee -a /var/log/vps-skill-bootcheck.log; }
report() { mkdir -p "$(dirname "$STATUS")"; echo "$1 $(date -Is) $2" > "$STATUS.tmp" && mv -f "$STATUS.tmp" "$STATUS"; }

run_checks() {
    problems=()
    local missing_ports=0 kind value
    while read -r kind value; do
        case "$kind" in
            unit)
                systemctl is-active --quiet "$value" && continue
                log "starting $value"
                systemctl restart "$value" >/dev/null 2>&1
                systemctl is-active --quiet "$value" || problems+=("unit $value")
                ;;
            tcp)
                ss -Htln "sport = :$value" | grep -q . || { problems+=("$value/tcp"); missing_ports=1; }
                ;;
            udp)
                ss -Huln "sport = :$value" | grep -q . || { problems+=("$value/udp"); missing_ports=1; }
                ;;
        esac
    done < "$CONFIG"
    if [ "$missing_ports" = 1 ] && [ "$attempt" = "$HEAL_AT" ]; then
        log "ports are missing, restarting x-ui"
        systemctl restart x-ui >/dev/null 2>&1
    fi
}

[ -f "$CONFIG" ] || { report FAILED "missing $CONFIG"; exit 1; }
sysctl --system >/dev/null 2>&1
[ -x "$FIREWALL" ] && { "$FIREWALL" >/dev/null 2>&1 || log "firewall rules could not be reapplied"; }

for attempt in $(seq 1 "$ATTEMPTS"); do
    run_checks
    if [ ${#problems[@]} -eq 0 ]; then
        report OK "attempt $attempt"
        log "OK after attempt $attempt"
        exit 0
    fi
    log "attempt $attempt: ${problems[*]}"
    sleep "$WAIT"
done
report FAILED "${problems[*]}"
log "FAILED: ${problems[*]}"
exit 1
"""

UNIT = """[Unit]
Description=vps-deploy-skill boot self-check
After=network-online.target x-ui.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/vps-skill-bootcheck
TimeoutStartSec=300
"""

TIMER_UNIT = """[Unit]
Description=Run the vps-deploy-skill boot self-check after every boot

[Timer]
OnBootSec=30s
AccuracySec=5s

[Install]
WantedBy=timers.target
"""


def render_config(units: Sequence[str], tcp: Sequence[int], udp: Sequence[int]) -> str:
    lines: List[str] = [f"unit {unit}" for unit in units]
    lines += [f"tcp {int(port)}" for port in sorted(set(tcp))]
    lines += [f"udp {int(port)}" for port in sorted(set(udp))]
    return "\n".join(lines) + "\n"


def install_script(units: Sequence[str], tcp: Sequence[int], udp: Sequence[int], firewall: str) -> str:
    files: Dict[str, str] = {
        CONFIG: render_config(units, tcp, udp),
        FIREWALL: "#!/bin/bash\n" + firewall,
        SCRIPT: CHECK_SCRIPT,
        SERVICE: UNIT,
        TIMER: TIMER_UNIT,
    }
    return web_profile.write_files_script(files) + f"""
chmod 700 {FIREWALL}
chmod 755 {SCRIPT}
systemctl daemon-reload
systemctl enable vps-skill-bootcheck.timer >/dev/null 2>&1
for u in {' '.join(units)}; do systemctl enable "$u" >/dev/null 2>&1 || true; done
echo BOOT_CHECK=installed
"""
