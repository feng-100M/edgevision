# 运行目录与数据

从仓库根目录运行项目。配置、模型、事件输出、虚拟环境、缓存和测试临时文件各自存放在项目内。部署到已有树莓派时先确认当前项目路径，保留设备的 `config.local.yaml`、模型、事件记录与截图。

`scripts/setup.sh` 将 Python 依赖装入项目内的 `.venv`。有完整离线轮包目录时使用 `.wheelhouse`，其余情况通过 pip 安装。`scripts/start_service.sh` 创建非 root 的临时 systemd 用户服务。Mosquitto 由设备管理员配置。

`EventStorage` 根据保留天数、数据量和磁盘空闲阈值，在专用输出目录内清理旧事件记录及其引用的 JPEG。现场媒体、凭据、真实设备配置和运行日志仅保存在本机。Git 发布范围由项目根目录的 [.gitignore](.gitignore) 控制。
