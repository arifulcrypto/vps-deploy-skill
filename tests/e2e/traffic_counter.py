#!/usr/bin/env python3
"""Run on the target: the deployment's client row must count real traffic."""
import sqlite3

rows = sqlite3.connect("/etc/x-ui/x-ui.db").execute(
    "SELECT down FROM client_traffics WHERE email LIKE 'vps-skill-%'").fetchall()
assert len(rows) == 1 and rows[0][0] > 1000000, f"client traffic was not counted: {rows}"
print("Client traffic counted")
