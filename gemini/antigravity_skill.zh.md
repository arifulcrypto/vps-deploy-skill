# Gemini / Google Antigravity Skill 指南（中文版）

本文档定义了在 **Google Antigravity** 智能编码助手或 Gemini CLI 中激活并调用 `vps-deployer` Skill 的核心执行流程。

## 会话中执行协议
1. **智能参数提取**：
   当用户以非结构化方式输入时，自动识别并提取主机 IP、SSH 端口、密码、可选域名、以及用户国内运营商归属。
2. **动态非固定高端口**：
   - 随机分配 Hysteria 2 UDP 端口（`30000-44999`）。
   - 随机分配 VLESS-Reality TCP 端口（`20000-29999`）。
   - 随机分配 3X-UI 面板端口（`45000-64000`）及随机安全路径。
   - 自动在目标主机上注入防火墙白名单放行规则。
3. **自动化工具链调用**：
   - 优先探测远端环境，发现占用端口的旧进程及时清理。
   - 调用 `python3 scripts/vps_deployer.py` 驱动全量端到端部署。
4. **Artifact 产物沉淀与双轨订阅**：
   - 在 Artifacts 目录生成完整报告 Markdown，并嵌入高清二维码图片（`![alt](/absolute/path)`）。
   - 输出标准的双轨 Clash Verge Rev 订阅链接（OnePage 主通道 + v1.mk 备用通道）。
   - 默认输出语言为英文（`en`），指定中文时输出中文。
