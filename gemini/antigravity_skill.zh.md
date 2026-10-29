# Gemini / Google Antigravity Skill 指南（中文）

Skill 通过 [`.agents/skills/vps-deployer/SKILL.md`](../.agents/skills/vps-deployer/SKILL.md) 自动发现（链接到根目录 [`SKILL.md`](../SKILL.md)，以其为准）。

## 会话执行流程
1. 从对话中提取 `ip`、SSH 端口/用户/凭据、可选域名与运营商；缺失项向用户询问。
2. 与用户确定方案（`reality-self` 需要灰云域名，否则用 `legacy`），写入配置 JSON，执行 `python3 scripts/vps_deployer.py --config <file> --dry-run`，展示计划并等待确认。
3. 使用 `run_command` 执行部署。不要对服务器执行临时的 `sshpass`/`systemctl`/`pkill` 命令，也不要自行修改面板数据库。
4. `--adopt-existing-panel`、`--stop-conflicting-services`、`--rotate-secrets`、`--online-sub` 仅在用户明确同意后使用。
5. 成功后根据 `result.json` 生成 Markdown 产物，包含面板访问方式、节点链接与二维码图片（`![node](/绝对路径/qr_<node>.png)`），并提示其中含有凭据；失败时汇报 `[ERROR]` 信息与 SKILL 排错条目。

默认输出英文（`en`）。
