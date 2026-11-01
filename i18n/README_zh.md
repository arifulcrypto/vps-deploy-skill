

## 重启规则

重启后无需人工处理。每次部署都会安装开机自检。

- 每次开机后 `vps-skill-bootcheck.timer` 会重新应用防火墙，启动 `x-ui` 和 Nginx，确认所有计划端口都在监听，端口持续缺失时重启一次 `x-ui`，结果写入 `/var/lib/vps-skill/boot-status`。
- 重启后等待 3 分钟再查看状态。`OK` 表示无需操作；`FAILED` 会列出异常项，查看 `/var/log/vps-skill-bootcheck.log`，修复后运行 `systemctl start vps-skill-bootcheck.service`。
- 不要把再次重启作为第一步。配合 vps-lxc-skill 时，还要查看宿主机的 `/var/lib/vps-lxc/boot-status`。
