---
name: vps-deployer
description: >-
  通过 SSH 在 Linux VPS 上部署并维护 3X-UI 代理节点。两种方案：`reality-self`（公网只开 TCP 443：
  VLESS-REALITY-Vision 的 target 指向运营者自己的 HTTPS 网站，非客户端访问看到的是正常网站）与
  `legacy`（REALITY 随机高端口、可选 Hysteria 2、Cloudflare 后的 443 VLESS-WS-TLS）。失败即停止，
  默认不动现有服务/入站/2FA，面板仅本机监听，重复部署复用已保存的密钥，产物仅属主可读。
---

# VPS Deployer Skill（中文）

英文版 [`SKILL.md`](../SKILL.md) 为准。引擎为 `scripts/vps_deployer.py`，智能体应调用它，而不是自行拼接远程命令。

## 一、行为原则

- **失败即停止（fail closed）**：所有远程步骤、监听检查、面板登录探测（以及 `reality-self` 的网站检查）全部通过后才写出报告、链接、二维码与 YAML。
- **默认无破坏**：不会停止已有 Web 服务（除非 `stop_conflicting_services`）；不是本 Skill 安装的 3X-UI 不会被改动（除非 `adopt_existing_panel`）。只修改标签为 `vps-skill-*` 的入站与 `vps-skill-<deploy_id>` 客户端；其他入站、客户端、2FA、面板证书保持不变。改库前自动备份并在单个事务中写入。
- **重复部署稳定**：UUID、密码、REALITY 密钥、端口与路径保存在服务器 `/etc/vps-skill/state.json`（0600）并复用，客户端链接不失效，防火墙规则不会累积。需要换新凭据时显式使用 `rotate_secrets`。
- **管理面私有**：面板（及 3X-UI 订阅服务）仅监听 `127.0.0.1`，通过 SSH 隧道访问；公网 HTTPS 面板需显式提供 `panel_domain`。
- **本地客户端配置**：`clash_config.yaml` 本地生成（`allow-lan: false`）。第三方订阅转换链接包含全部凭据，仅在 `online_sub` 时生成。
- **不承诺"不可封锁"**：任何方案都不能保证不被识别或封锁，请以用户网络的实际可用性为准。

## 二、部署方案

| | `reality-self`（有域名时推荐） | `legacy`（默认） |
| :--- | :--- | :--- |
| 公网 TCP | 80（ACME + 跳转）、443 | REALITY 高端口；设置 `domain` 时另开 80/443 |
| 公网 UDP | 仅 `enable_hy2` 时开放 Hysteria 2 | Hysteria 2 随机高端口（默认开启） |
| REALITY target | `127.0.0.1:8443` 自有 Nginx 网站，`xver: 1` | `reality_sni:443`（默认 `addons.mozilla.org`） |
| 扫描者在 443 看到 | 运营者自己的网站与该域名的有效证书 | Cloudflare 后的 Xray WS-TLS |
| DNS | `domain` **仅 DNS（灰云）** | `domain` 开启 Cloudflare 代理（橙云）用于 WS |
| 证书 | acme.sh webroot（Nginx），续期后 reload Nginx | acme.sh standalone 占用 :80，续期后重启 x-ui |

```text
客户端 ──TLS(SNI=domain)──▶ :443 Xray VLESS+REALITY+Vision ──合法客户端──▶ 互联网
                                   └─ 其他连接（PROXY v1）─▶ 127.0.0.1:8443 Nginx ─▶ 静态网站
:80 Nginx ─ /.well-known/acme-challenge/；其余 301 跳转 https
```

`legacy` 已知局限：REALITY 会把未认证连接转发到外部 target，扫描者可借此端口中转访问该网站；VPS IP 上出现他人证书也是可观测的 SNI/IP 不匹配。`reality-self` 可避免这两点。

## 三、输入参数

参数含义与英文版第 3 节相同。必填：`ip`、`ssh_pass` 或 `ssh_key`（`ssh_pass` 也可通过环境变量 `VPS_SSH_PASS` 提供）；`reality-self` 还需要 `domain`。
选择 `reality-self` 前，请确认用户拥有灰云域名，且其网络可以直连该 VPS 的 HTTPS。
`adopt_existing_panel`、`stop_conflicting_services`、`rotate_secrets`、`reinstall_xui`、`online_sub` 均为显式开关，使用前须征得用户同意。

## 四、智能体执行流程

1. **收集并确认**：整理参数，与用户确定方案，先执行 `python3 scripts/vps_deployer.py --config <file> --dry-run`，展示计划（端口、对外开放端口、证书域名）并获得确认。
2. **执行**：`python3 scripts/vps_deployer.py --config <file>`。阶段：只读预检 → 软件包/BBR/防火墙 → 证书（+网站）→ 3X-UI → 入站（冲突检查、备份、事务）→ 验证 → 本地产物。
3. **失败时**：进程以非零退出并输出 `[ERROR] ...`，不生成产物。转述错误并参考第五节；仅在合适时建议对应开关。不要手动改面板数据库或强杀进程来绕过。
4. **交付**：读取 `<output_dir>/result.json`，向用户展示方案、面板访问方式（SSH 隧道命令、地址、用户名、密码）、节点名称与链接、`clash_config.yaml` 与二维码路径以及 `notes`，并提醒这些文件包含凭据。

## 五、常见错误

| 错误 | 含义 | 处理 |
| :--- | :--- | :--- |
| `3X-UI is already installed but not managed by this skill` | 发现非本 Skill 管理的面板 | 询问用户；确认归属后才使用 `adopt_existing_panel` |
| `Port conflicts detected ...` | Web 服务占用所需端口 | 询问用户；`stop_conflicting_services` 只停用该服务。`reality-self` 下 443 上的 Nginx 需手动迁移到 `127.0.0.1:8443` |
| `certificate issuance failed` | ACME 失败（不会回退自签证书） | 检查 A/AAAA 记录、`reality-self`/`panel_domain` 需灰云、80 端口可达 |
| `Inbound configuration failed: port conflict` | 已有入站占用计划端口 | 更换端口或由用户自行处理该入站 |
| `Expected listeners missing` | Xray 拒绝了配置 | 查看日志摘录；可考虑固定 `xui_version` |
| `Panel login verification failed` | 凭据未通过验证（未做任何重置） | 若开启了 2FA，请手动登录确认 |
| `Port 443 did not serve the deployed website` | REALITY → Nginx 链路异常 | 检查 `nginx -t` 与 `/etc/nginx/conf.d/vps-skill.conf` |
