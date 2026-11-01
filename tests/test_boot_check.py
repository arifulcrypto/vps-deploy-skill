"""The boot self-check is real bash: run it with fake systemctl and ss on PATH."""
import os
import stat
import subprocess

import pytest

from scripts import boot_check

SYSTEMCTL = r"""#!/bin/bash
S=$STATE_DIR
case "$1" in
is-active) [ -f "$S/up_$3" ] ;;
restart) echo "restart $2" >> "$S/actions"; touch "$S/up_$2"; [ "$2" = x-ui ] && [ -f "$S/heal_ports" ] && touch "$S/ports" ; true ;;
esac
"""
SS = r"""#!/bin/bash
[ -f "$STATE_DIR/ports" ] && echo LISTEN
"""


@pytest.fixture
def box(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {"systemctl": SYSTEMCTL, "ss": SS, "sysctl": "#!/bin/bash\n"}.items():
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    firewall = tmp_path / "firewall.sh"
    firewall.write_text('#!/bin/bash\necho firewall >> "$STATE_DIR/actions"\n')
    firewall.chmod(0o755)
    script = boot_check.CHECK_SCRIPT.replace("/etc/vps-skill/boot-check.conf", str(tmp_path / "conf")) \
        .replace("/etc/vps-skill/firewall.sh", str(firewall)) \
        .replace("/var/lib/vps-skill/boot-status", str(tmp_path / "status")) \
        .replace("/var/log/vps-skill-bootcheck.log", str(tmp_path / "log")) \
        .replace('export PATH="$PATH:/usr/sbin:/sbin"', f'export PATH="{bin_dir}:$PATH"')
    (tmp_path / "check.sh").write_text(script)
    (tmp_path / "conf").write_text(boot_check.render_config(["x-ui"], [443], [31000]))

    def run(attempts="6"):
        env = dict(os.environ, STATE_DIR=str(tmp_path), BOOTCHECK_ATTEMPTS=attempts, BOOTCHECK_WAIT="0")
        return subprocess.run(["bash", str(tmp_path / "check.sh")], env=env, capture_output=True, text=True)

    obj = type("Box", (), {})()
    obj.run, obj.path = run, tmp_path
    obj.actions = lambda: (tmp_path / "actions").read_text().split("\n")
    return obj


def test_healthy_boot_reports_ok(box):
    (box.path / "up_x-ui").touch()
    (box.path / "ports").touch()
    assert box.run().returncode == 0
    assert (box.path / "status").read_text().startswith("OK ")


def test_firewall_is_reapplied_on_every_boot(box):
    (box.path / "up_x-ui").touch()
    (box.path / "ports").touch()
    box.run()
    assert "firewall" in box.actions()


def test_stopped_service_is_started(box):
    (box.path / "ports").touch()
    assert box.run().returncode == 0
    assert "restart x-ui" in box.actions()


def test_missing_ports_restart_the_panel_once(box):
    (box.path / "up_x-ui").touch()
    (box.path / "heal_ports").touch()
    assert box.run().returncode == 0
    assert box.actions().count("restart x-ui") == 1


def test_lasting_failure_is_reported(box):
    (box.path / "up_x-ui").touch()
    assert box.run(attempts="2").returncode == 1
    status = (box.path / "status").read_text()
    assert status.startswith("FAILED ") and "443/tcp" in status and "31000/udp" in status


def test_install_enables_the_timer_and_services():
    script = boot_check.install_script(["x-ui", "nginx"], [443], [], "echo fw\n")
    assert "systemctl enable vps-skill-bootcheck.timer" in script and 'systemctl enable "$u"' in script
    assert subprocess.run(["bash", "-n"], input=script, text=True).returncode == 0
