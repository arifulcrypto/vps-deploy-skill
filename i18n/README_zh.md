# VPS Deployer Skill

> 由 AI 智能体或命令行在 Linux VPS 上部署并维护 3X-UI 代理节点。
> *支持 OpenAI GPTs、Anthropic Claude、Google Gemini / Antigravity 以及独立 CLI。*

[English](../README.md) | [中文说明](./README_zh.md)

---

## 概览

- **两种方案**：`reality-self` 只使用 TCP 443——合法的 VLESS-REALITY-Vision 客户端走代理，其余连接经本机 Nginx 看到运营者自己的 HTTPS 网站；`legacy` 保留多端口布局（REALITY 随机高端口、可选 Hysteria 2、Cloudflare 后的 443 VLESS-WS-TLS）。
- **失败即停止**：任何远程步骤、监听检查、面板登录探测或网站检查失败都不会生成报告、链接或二维码；ACME 失败直接报错，不会悄悄换成自签证书。
- **默认无破坏**：不动已有 Web 服务、其他 3X-UI 入站与客户端、2FA 和面板证书；破坏性操作需显式开关。改库前备份并在单个事务中写入。
- **重复部署稳定**：身份、密钥与端口保存在服务器 `/etc/vps-skill/state.json` 并复用；防火墙规则幂等管理（ufw、firewalld 或独立 iptables 链）。
- **默认私有**：面板仅监听 `127.0.0.1`（SSH 隧道访问）；产物在 0700 目录中以 0600 写入；Clash YAML 本地生成，第三方转换需显式开启。

完整参数、执行流程与排错见 [`SKILL_zh.md`](./SKILL_zh.md)（以英文 [`SKILL.md`](../SKILL.md) 为准）。

## 快速开始

```bash
git clone https://github.com/arifulcrypto/vps-deploy-skill.git
cd vps-deploy-skill
pip install -r requirements.txt          # 密码登录需本机安装 openssh-client 与 sshpass

# 1. 仅生成计划（不改动服务器）
python3 scripts/vps_deployer.py --config examples/input_reality_self.json --dry-run

# 2. 正式部署（密码通过环境变量传入，避免出现在进程参数中）
VPS_SSH_PASS='...' python3 scripts/vps_deployer.py --config examples/input_reality_self.json
```

`reality-self` 需要一个指向 VPS 的 **仅 DNS（灰云）** A 记录。常用参数：

| 参数 | 作用 |
| :--- | :--- |
| `--profile {legacy,reality-self}` | 部署方案（默认 `legacy`） |
| `--domain`、`--ipv6-domain`、`--panel-domain` | 域名（各方案的 DNS 模式见 SKILL） |
| `--hy2 / --no-hy2` | 开关 Hysteria 2 |
| `--ssh-key`、`--ssh-known-hosts` | 密钥登录；预置主机指纹，替代首次信任 |
| `--xui-version v3.11.0` | 固定 3X-UI 版本 |
| `--adopt-existing-panel` | 接管非本 Skill 安装的 3X-UI |
| `--stop-conflicting-services` | 停止并禁用占用 80/443 的 Web 服务 |
| `--rotate-secrets` | 生成新的 UUID/密码/REALITY 密钥（旧链接失效） |
| `--online-sub` | 额外输出第三方订阅转换链接（会把凭据发送给对方） |

## 输出

```text
output/<ip>/                 （目录 0700，文件 0600——包含凭据）
├── vps_<ip>_info.txt        报告（链接与终端二维码）
├── result.json              机器可读结果
├── clash_config.yaml        本地 Clash/Mihomo 配置
└── qr_<节点>.png             二维码
```

## 开发

```bash
pip install -r requirements-dev.txt
ruff check scripts tests && pytest -q
```

## 许可证

MIT，详见 [LICENSE](../LICENSE)。
