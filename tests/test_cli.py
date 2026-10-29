"""CLI behaviour."""
import json
import subprocess
import sys


def run(*args):
    return subprocess.run([sys.executable, "scripts/vps_deployer.py", *args], capture_output=True, text=True)


def test_cli_help_flag():
    res = run("--help")
    assert res.returncode == 0
    assert "VPS Multi-Protocol Deployment Automation Engine" in res.stdout


def test_module_entry_point():
    res = subprocess.run([sys.executable, "-m", "scripts.vps_deployer", "--help"], capture_output=True, text=True)
    assert res.returncode == 0


def test_cli_dry_run_mode(tmp_path):
    res = run("--ip", "198.51.100.1", "--ssh-pass", "secret123", "--output-dir", str(tmp_path / "o"), "--dry-run")
    assert res.returncode == 0, res.stderr
    assert "DRY-RUN" in res.stdout
    assert not (tmp_path / "o").exists()


def test_config_values_are_not_overridden_by_cli_defaults(tmp_path):
    conf = tmp_path / "c.json"
    conf.write_text(json.dumps({"ip": "198.51.100.1", "ssh_pass": "x", "ssh_port": 2222,
                                "profile": "reality-self", "domain": "www.example.com"}))
    res = run("--config", str(conf), "--dry-run")
    assert res.returncode == 0, res.stderr
    assert "root@198.51.100.1:2222" in res.stdout and "reality-self" in res.stdout


def test_invalid_input_exits_nonzero():
    res = run("--ip", "198.51.100.1", "--ssh-pass", "x", "--domain", "a.com;id", "--dry-run")
    assert res.returncode == 1 and "Invalid domain" in res.stderr
