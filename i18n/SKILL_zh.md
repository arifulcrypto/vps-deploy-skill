---
name: vps-deployer-zh
description: >-
  自动化多协议海外 VPS 极速部署与集群管理 Skill。
  基于动态高端口部署 3X-UI，配置 Hysteria 2（动态高 UDP 端口，Salamander 混淆）、
  VLESS-Reality（动态高 TCP 端口，Vision 流控）与 VLESS-WS-TLS（443 端口走 Cloudflare Anycast CDN 与三大运营商优选 IP）。
  签发双域名 Let's Encrypt ECC 证书，生成终端 ASCII 与高清 PNG 二维码，
  下载离线 Clash YAML 规则，直出双轨 OnePage & 备用 Clash Verge Rev 订阅链接。
---

# VPS 多协议自动化部署与集群管理 Skill（中文版）

## 1. 概述与核心能力

**VPS Deployer Skill** 专为 AI 结对编程助手与自动化 Agent（全面适配 OpenAI GPTs、Claude Desktop / Code、Gemini CLI、Google Antigravity）打造，实现海外 VPS 从纯裸机到多协议集群的全自动一键交付。

### 核心特性：
1. **动态非固定高端口架构（去特征化抗封锁）**：
   - **Hysteria 2**：随机分配动态高 UDP 端口（如 `30000-44999`），基于 QUIC + BBR 拥塞控制与随机 Salamander 混淆密码，彻底消除 TCP 队头阻塞，晚高峰即使 30% 丢包照样跑满宽带。
   - **VLESS-Reality**：随机分配动态高 TCP 端口（如 `20000-29999`），借壳 Mozilla 官方证书与流量特征，避开 GFW 对海外 443 端口的主动探测，1-RTT 极速握手，秒开 4K/8K 视频。
   - **3X-UI 控制面板**：随机分配动态高 TCP 端口（如 `45000-64000`），挂载随机生成的安全路径（`/<随机Token>/`）。
   - **VLESS-WS-TLS（443 端口）**：走 Cloudflare Anycast CDN，挂载联通/移动/电信专属 Anycast Clean IP，打造全天候抗封锁复活甲。
2. **双域名 Let's Encrypt ECC SAN 证书**：
   - 自动支持 IPv4 域名与 IPv6 域名联合签发，彻底解决 IPv6 回源触发 Cloudflare 526 SSL 握手报错。
3. **双轨 Clash 订阅冗余交付（主备双通道）**：
   - **🔥 主订阅**：OnePage Sub-Convert 在线直出订阅，内置 **ACL4SSR_Online_Full_NoAuto** 规则，国内应用强制 DIRECT 本地直连免流。
   - **🛡️ 备用订阅**：v1.mk 备用订阅转换通道，防止单点转换故障。
   - **💾 离线备份**：本地归档目录保存下载好的 `clash_config.yaml`，离线即可导入使用。
4. **Agent 认知自愈与边际自适应能力**：
   - Agent 不只是机械运行脚本，而是具备自主探测、防火墙动态开标、历史进程清理与动态 SQLite 结构适配能力的自愈智能体。

---

## 2. 输入参数规范

Agent 接收到用户指令后，解析或提示输入以下关键字段：

| 参数名称 | 类型 | 必填 | 默认值 | 说明 | 示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ip` | 字符串 | **是** | — | VPS 公网 IPv4 地址 | `198.51.100.1` |
| `ssh_port` | 整数 | 否 | `22` | SSH 连接端口 | `22` 或 `4400` |
| `ssh_user` | 字符串 | 否 | `root` | SSH 用户名 | `root` |
| `ssh_pass` | 字符串 | **是** | — | SSH 登录密码 | `your_secure_password` |
| `domain` | 字符串 | 否 | `None` | IPv4 绑定的域名（Cloudflare 橙色小云朵开启） | `node.yourdomain.com` |
| `ipv6` | 字符串 | 否 | `None` | 公网 IPv6 地址 | `2001:db8:85a3::1` |
| `ipv6_domain` | 字符串 | 否 | `None` | IPv6 绑定的专属域名 | `ipv6.yourdomain.com` |
| `client_isp` | 字符串 | 否 | `unicom` | 用户客户端运营商（`unicom` / `mobile` / `telecom` / `overseas`） | `unicom` |
| `client_ip` | 字符串 | 否 | `通用` | 用户国内出口 IP | `203.0.113.50` |
| `client_loc` | 字符串 | 否 | `区域中心` | 用户物理归属地 | `区域中心城市` |
| `panel_port` | 整数 | 否 | *随机* | 3X-UI 面板端口 | 随机 `45000-64000` |
| `hy2_port` | 整数 | 否 | *随机* | Hysteria 2 UDP 端口 | 随机 `30000-44999` |
| `reality_port`| 整数 | 否 | *随机* | VLESS-Reality TCP 端口 | 随机 `20000-29999` |
| `output_dir` | 字符串 | 否 | `./output/<ip>` | 资产存放目录 | `./output/198.51.100.1` |
| `lang` | 字符串 | 否 | `en` | 默认语言为 `en`，指定中文时为 `zh` | `en` 或 `zh` |

---

## 3. Agent 认知执行 SOP

```
[步骤 1: 环境探测、系统防火墙适配与端口冲突清理]
       │
       ▼
[步骤 2: Let's Encrypt ECC 双域名证书签发与挂载]
       │
       ▼
[步骤 3: 3X-UI 非交互式动态高端口部署]
       │
       ▼
[步骤 4: SQLite 数据库动态 Inbounds 注入]
       │
       ▼
[步骤 5: 端口校验与 WebSocket 端到端握手测试]
       │
       ▼
[步骤 6: 资产落盘、二维码生成与双轨 Clash 订阅直出]
```

### 步骤 1：环境探测与防火墙动态放行
1. 检查 BBR 状态并开启：`net.ipv4.tcp_congestion_control = bbr`。
2. 停用并禁用可能霸占 80 或 443 端口的残留 web 服务：
   `systemctl stop xray nginx apache2 caddy 2>/dev/null || true`
3. 动态生成随机高端口后，主动检测并放行本地防火墙（`ufw` / `iptables`）：
   ```bash
   which ufw >/dev/null 2>&1 && (ufw allow <panel_port>/tcp; ufw allow <reality_port>/tcp; ufw allow <hy2_port>/udp; ufw allow 443/tcp; ufw allow 80/tcp) || true
   which iptables >/dev/null 2>&1 && (iptables -I INPUT -p tcp --dport <panel_port> -j ACCEPT; iptables -I INPUT -p tcp --dport <reality_port> -j ACCEPT; iptables -I INPUT -p udp --dport <hy2_port> -j ACCEPT; iptables -I INPUT -p tcp --dport 443 -j ACCEPT) || true
   ```

### 步骤 2：SSL 证书签发
若提供了域名，通过 `acme.sh` Standalone 模式签发：
- 若同时有 IPv4 与 IPv6 域名：`-d <domain> -d <ipv6_domain>`
- 证书安装路径：`/root/cert/<domain>/fullchain.pem` 和 `privkey.pem`。

### 步骤 3：3X-UI 非交互安装
```bash
export XUI_NONINTERACTIVE=1
export XUI_USERNAME="admin"
export XUI_PASSWORD="<ssh_pass>"
export XUI_PANEL_PORT="<panel_port>"
export XUI_WEB_BASE_PATH="<panel_base_path>"
curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh | bash
```

### 步骤 4：SQLite 注入多协议 Inbounds
使用 `scripts/db_configurator.py` 写入 `/etc/x-ui/x-ui.db`：
1. Inbound 1: 端口 `443` (VLESS-WS-TLS)，`wsSettings.headers = {}`。
2. Inbound 2: 端口 `<hy2_port>` UDP (Hysteria 2)，随机 Salamander 混淆，QUIC BBR。
3. Inbound 3: 端口 `<reality_port>` TCP (VLESS-Reality)，`xtls-rprx-vision`，SNI `addons.mozilla.org`。
4. 重启 `systemctl restart x-ui`。

### 步骤 5：端到端连通性测试
1. 端口监听检测：`ss -tulpn` 确认 `<hy2_port>`、`<reality_port>`、`443`、`<panel_port>` 在线。
2. WebSocket 回源检测：
   ```bash
   curl -sS -v -H "Upgrade: websocket" -H "Connection: Upgrade" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" -H "Sec-WebSocket-Version: 13" https://<domain>/ws
   ```
   预期响应：`HTTP/2 400 sec-websocket-version: 13 Bad Request`（证明 Xray WebSocket 回源成功）。

### 步骤 6：生成资产、二维码与双轨 Clash 订阅
1. 组装客户端节点链接（Hy2、Reality、联通/移动/电信优选 IP、标准 443）。
2. 调用 `scripts/qr_engine.py` 生成高清图片与终端 ASCII 二维码。
3. 调用 `scripts/sub_converter.py` 获取**双轨 Clash Verge Rev 订阅链接**（OnePage 主通道 + v1.mk 备用通道）并下载离线 `clash_config.yaml`。
4. 生成结构化 `.txt` 归档并向用户输出结果。

---

## 4. 故障排除速查表

| 常见报错 / 现象 | 根因深度剖析 | 自动修复方案 |
| :--- | :--- | :--- |
| `sqlite3.OperationalError: no column named exclude_from_sub` | 3X-UI 跨版本数据库字段变更 | 动态查询 `PRAGMA table_info(inbounds)` 适配插入字段。 |
| 国内 `curl --resolve "domain:443:vps_ip"` 报 5 秒超时 | 国内运营商省级网关对境外裸 443 端口主动丢包 | 严禁直连裸 443。直连必须走高端口（`<reality_port>` / `<hy2_port>`）；443 必须走 Cloudflare CDN 或 Anycast Clean IP。 |
| IPv6 域名访问报 Cloudflare 526 错误 | VPS 原站证书仅签发了 IPv4 域名 | 使用 `acme.sh` 签发同时包含 IPv4 和 IPv6 的 SAN 证书。 |
| WebSocket 回源报 404 | Xray inbound 中的 Host 头部被写死 | 将 `wsSettings.headers` 留空 `{}`，允许任意合法域名回源握手。 |
| 随机高端口无法连接 | 系统内部启用了 `ufw` 或 `iptables` | 在第一阶段自动检测并注入对应端口的 TCP/UDP 放行规则。 |
