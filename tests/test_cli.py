"""Test CLI behavior."""
import subprocess
import sys


def test_cli_help_flag():
    res = subprocess.run([sys.executable, "scripts/vps_deployer.py", "--help"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "VPS Multi-Protocol Deployment Automation Engine" in res.stdout


def test_cli_dry_run_mode():
    cmd = [
        sys.executable, "scripts/vps_deployer.py",
        "--ip", "198.51.100.1",
        "--ssh-pass", "secret123",
        "--dry-run"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "DRY-RUN MODE: Validation passed" in res.stdout
