#!/usr/bin/env python3
"""
Report & Artifact Writer:
Renders the bilingual text report and writes every artifact with owner-only
permissions (directory 0700, files 0600), since they contain credentials.
"""
import json
import os
from typing import Any, Dict, List

RULE = "-" * 80
BANNER = "=" * 80

LABELS = {
    "en": {
        "title": "VPS Deployment Archive",
        "server": "Server", "profile": "Profile", "domain": "Domain", "ipv6": "IPv6", "client": "Client network",
        "generated": "Generated", "none": "not configured",
        "s_access": "1. Server & Panel Access",
        "ssh": "SSH", "panel": "3X-UI panel", "panel_user": "Panel user", "panel_pass": "Panel password",
        "panel_private": "Private (loopback only). Open an SSH tunnel first:",
        "panel_public": "Public HTTPS on a dedicated panel domain",
        "s_nodes": "2. Client Nodes", "link": "Link", "qr": "Terminal QR",
        "s_subs": "3. Online Subscription Converters (opt-in, credentials are sent to these services)",
        "s_files": "4. Local Files (owner-only permissions)", "s_notes": "5. Notes",
    },
    "zh": {
        "title": "VPS 部署档案",
        "server": "服务器", "profile": "部署方案", "domain": "域名", "ipv6": "IPv6", "client": "客户端网络",
        "generated": "生成时间", "none": "未配置",
        "s_access": "一、服务器与面板访问",
        "ssh": "SSH", "panel": "3X-UI 面板", "panel_user": "面板用户", "panel_pass": "面板密码",
        "panel_private": "仅本机监听（不对公网开放）。请先建立 SSH 隧道：",
        "panel_public": "独立面板域名 HTTPS 公网访问",
        "s_nodes": "二、客户端节点", "link": "链接", "qr": "终端二维码",
        "s_subs": "三、在线订阅转换（需显式开启，节点凭据会发送给第三方服务）",
        "s_files": "四、本地文件（仅属主可读写）", "s_notes": "五、说明",
    },
}


def render_report(ctx: Dict[str, Any], lang: str = "en") -> str:
    L = LABELS.get(lang, LABELS["en"])
    p = ctx["panel"]
    out: List[str] = [
        BANNER, f"  {L['title']}", BANNER,
        f"{L['server']:<16}: {ctx['ip']}",
        f"{L['ipv6']:<16}: {ctx.get('ipv6') or L['none']}",
        f"{L['domain']:<16}: {ctx.get('domain') or L['none']}",
        f"{L['profile']:<16}: {ctx['profile']}",
        f"{L['client']:<16}: {ctx['client_isp']} ({ctx['client_location']} | {ctx['client_ip']})",
        f"{L['generated']:<16}: {ctx['timestamp']}",
        "", RULE, L["s_access"], RULE,
        f"{L['ssh']:<16}: ssh -p {ctx['ssh_port']} {ctx['ssh_user']}@{ctx['ip']}",
        f"{L['panel']:<16}: {p['url']}",
        f"{L['panel_user']:<16}: {p['user']}",
        f"{L['panel_pass']:<16}: {p['pass']}",
    ]
    if p["public"]:
        out.append(f"{'':<16}  {L['panel_public']}")
    else:
        out += [f"{'':<16}  {L['panel_private']}", f"{'':<16}  {p['tunnel']}"]

    out += ["", RULE, L["s_nodes"], RULE]
    for node in ctx["nodes"]:
        out += [f"[{node['name']}]  ({node['route']})", f"{L['link']}: {node['uri']}"]
        if node.get("ascii_qr"):
            out += [f"{L['qr']}:", node["ascii_qr"]]
        out.append("")

    if ctx.get("online_subs"):
        out += [RULE, L["s_subs"], RULE]
        out += [f"{i}. {url}" for i, url in enumerate(ctx["online_subs"], 1)]
        out.append("")

    out += [RULE, L["s_files"], RULE]
    out += [f"- {k}: {v}" for k, v in ctx["files"].items()]
    if ctx.get("notes"):
        out += ["", RULE, L["s_notes"], RULE]
        out += [f"- {n}" for n in ctx["notes"]]
    out.append(BANNER)
    return "\n".join(out) + "\n"


def secure_dir(path: str) -> str:
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def write_secret(path: str, content: str) -> str:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(path, 0o600)
    return path


def write_secret_json(path: str, data: Dict[str, Any]) -> str:
    return write_secret(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
