#!/usr/bin/env python3
"""
Remote Transport:
Runs shell and Python scripts on the target over SSH. Scripts and secret
payloads travel over stdin, so nothing sensitive appears in local or remote argv.
"""
import base64
import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, Optional


class DeploymentError(Exception):
    """Raised when a deployment step fails; no success artifacts are produced."""


@dataclass
class SSHTarget:
    host: str
    port: int = 22
    user: str = "root"
    password: Optional[str] = None
    key_file: Optional[str] = None
    known_hosts: Optional[str] = None

    def _command(self, remote_command: str):
        opts = ["-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-p", str(self.port)]
        if self.known_hosts:
            # Pre-provisioned, independently verified host key (no trust-on-first-use)
            opts += ["-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={self.known_hosts}"]
        else:
            opts += ["-o", "StrictHostKeyChecking=accept-new"]

        env = os.environ.copy()
        if self.key_file:
            cmd = ["ssh"] + opts + ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-i", self.key_file]
        else:
            cmd = ["ssh"] + opts
        cmd += [f"{self.user}@{self.host}", remote_command]

        if self.password and not self.key_file:
            env["SSHPASS"] = self.password
            cmd = ["sshpass", "-e"] + cmd
        return cmd, env

    def run(self, remote_command: str, input: Optional[str] = None, timeout: int = 120,
            check: bool = True, name: str = "remote command") -> subprocess.CompletedProcess:
        cmd, env = self._command(remote_command)
        try:
            res = subprocess.run(cmd, input=input, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise DeploymentError(f"{name}: timed out after {timeout}s on {self.host}")
        except FileNotFoundError as e:
            raise DeploymentError(f"Local dependency missing: {e.filename} (install openssh-client / sshpass)")

        if res.returncode == 255:
            err = res.stderr.strip()
            if "Permission denied" in err:
                raise DeploymentError(f"SSH authentication failed for {self.user}@{self.host}:{self.port}.")
            if "REMOTE HOST IDENTIFICATION HAS CHANGED" in err or "Host key verification failed" in err:
                raise DeploymentError(f"SSH host key verification failed for {self.host}. Verify the server fingerprint.")
            if "timed out" in err or "unreachable" in err:
                raise DeploymentError(f"SSH connection to {self.host}:{self.port} timed out or host unreachable.")
            if "Connection refused" in err:
                raise DeploymentError(f"SSH connection refused on {self.host}:{self.port}.")
            raise DeploymentError(f"SSH error: {err[:300]}")
        if check and res.returncode != 0:
            detail = (res.stderr.strip() or res.stdout.strip())[-600:]
            raise DeploymentError(f"{name} failed (exit {res.returncode}): {detail}")
        return res

    def run_script(self, name: str, script: str, timeout: int = 180, check: bool = True) -> subprocess.CompletedProcess:
        """Run a bash script fed through stdin."""
        return self.run("bash -s", input=script, timeout=timeout, check=check, name=name)

    def run_python(self, name: str, script: str, payload: Dict[str, Any], timeout: int = 60,
                   check: bool = True) -> subprocess.CompletedProcess:
        """Run a static Python script (argv, base64) with its JSON payload on stdin."""
        b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
        command = f"python3 -c 'import base64;exec(base64.b64decode(\"{b64}\").decode())'"
        return self.run(command, input=json.dumps(payload), timeout=timeout, check=check, name=name)


def last_json_line(text: str) -> Optional[Dict[str, Any]]:
    """Return the last line of output that parses as a JSON object."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def parse_kv(text: str) -> Dict[str, str]:
    """Parse KEY=VALUE lines emitted by provisioning scripts."""
    out = {}
    for line in text.splitlines():
        if "=" in line and line.split("=", 1)[0].isupper():
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out
