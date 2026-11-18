# 运行指南

## Windows 视频回放

在仓库根目录的 PowerShell 中运行以下命令。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\edgevision.exe assets
.\.venv\Scripts\edgevision.exe replay --frames 100 --mode sync --no-mqtt
```

## 树莓派服务与消息订阅

在树莓派 Wayland 桌面会话下，`sh scripts/run.sh` 可启动检测并打开 Chromium。无桌面环境的预览访问方法见[项目主页](../README.md#摄像头与实时预览)。

临时用户服务通过 `sh scripts/start_service.sh` 启动，以 `systemctl --user stop edgevision-reproduction.service` 停止。

启用 MQTT 时，先准备 Mosquitto，核对配置中的主机和主题，运行检测时移除 `--no-mqtt`。另开终端运行 `mosquitto_sub -h 127.0.0.1 -t edgevision/alerts -v` 可观察消息。程序分别记录客户端接受发布和代理收到后返回的 QoS 1 确认。

## 模型与验证

要复现 320 模型，先下载素材，再运行 `.venv/bin/python -m pip install -e '.[model_tools]'` 和 `.venv/bin/python scripts/build_fast_model.py --size 320`，然后将本地配置的 `model.path` 改为 `models/yolox_nano_320.onnx`。原始模型及派生权重的来源和校验值见[模型清单](../models/manifest.json)。

```bash
.venv/bin/python -m pytest -q -rs
.venv/bin/edgevision model-manifest
```


## 帧交接与运行指标

| 交接位置 | 过载时的行为 |
| --- | --- |
| UVC 子进程 → 主进程 | 子进程以非阻塞操作交帧。满时尝试取走积压帧并再放一次，仍满则跳过本次发送。主进程可在读帧超时后重启子进程。 |
| 主进程采集线程 → 推理循环（`latest`） | 一个待处理帧槽。生产者在同一把锁下替换旧帧并唤醒消费者，消费者取走帧后释放锁，再执行推理。 |
| 推理循环 → 事件输出线程 | 独立的有界 FIFO 保存待写事件。满时记录 `output_queue_dropped`，用于定位存储或告警输出过载。 |

例如推理正在处理 A，B 和 C 先后到达应用队列，C 会替换 B。A 完成后直接取 C。队列为空时消费者睡眠等帧。容量 1 限制应用层积压，对短时目标的覆盖率取决于实际处理频率。要逐帧复核录像，可用 `replay --mode sync`。摄像头的驱动缓冲、跨进程传输和一次模型计算仍会贡献延迟。

| 运行指标 | 实际测量范围 |
| --- | --- |
| `camera_ipc_skipped_frames` | 同次相机子进程读取序号在主进程出现的缺口。只统计到已收到的帧，无法测量传感器漏采。保留旧字段 `camera_driver_dropped_frames`。 |
| `queue_dropped_frames`、`queue_drop_rate` | 应用线程队列替换的帧数，比例以交到主进程流水线的帧数为分母。 |
| `app_queue_wait_p95_ms` | 已取出帧从应用入队到出队的 p95。同步模式或无样本时为 `null`。 |
| `max_queue_wait_ms`、`end_to_end_p95_ms` | 前者是历史命名，记录软件读帧完成到应用出队的最大帧龄。后者记录读帧完成到检测处理完成的 p95。均不含曝光时间。 |
| `storage_failed`、`output_queue_dropped`、`mqtt_failed` | 分别指向证据写入、事件排队和消息发布环节。 |
