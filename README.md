# EdgeVision · 树莓派离线区域入侵检测

EdgeVision 在 Raspberry Pi 5 上从 USB 摄像头读取视频，用 YOLOX-Nano 检测人员，按轨迹判断人员何时进入或离开指定区域。告警可保存为 JSONL 和现场截图，也可通过 MQTT 发送。整条检测链路在设备本地运行，首次下载依赖及公开模型后即可离线使用。

## 五分钟跑通视频回放

在有 Python 3.11 或 3.12 的 Linux 环境中，使用公开视频即可运行。Raspberry Pi OS 建议使用 64 位系统，并安装对应 Python 的 venv 组件。以下命令从新克隆开始。

```bash
git clone https://github.com/feng-100M/edgevision.git
cd edgevision
sh scripts/setup.sh
.venv/bin/edgevision assets
.venv/bin/edgevision replay --frames 100 --mode sync --no-mqtt --json-out benchmarks/results/replay.json
```

最后一条命令在终端打印 JSON，并把相同的汇总写入文件。检查 `processed_frames`、`errors` 和 `events`。在 `output/YYYY-MM-DD/events.jsonl` 可查看进入、离开时间及对应的截图路径。模糊画面仍记录事件，截图字段为空。使用 Windows PowerShell 时，可运行 `py -3.12 -m venv .venv` 和 `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`，随后用 `.\.venv\Scripts\edgevision.exe` 运行相同子命令。

## 摄像头运行

接入 UVC 摄像头，在仓库根目录执行下列命令。将 `config.local.yaml` 中的 `input.device` 指向自己的视频设备，再根据画面调整 `rotation`、`mirror_horizontal` 和 `roi.points`。示例配置使用官方 416×416 模型。

```bash
cp -n config.example.yaml config.local.yaml
.venv/bin/edgevision check --config config.local.yaml --input uvc --duration 5
.venv/bin/edgevision run --config config.local.yaml --input uvc --mode latest \
  --duration 60 --preview --no-mqtt --json-out benchmarks/results/camera.json
```

预览页位于 [本机 8765 端口](http://127.0.0.1:8765)。页面显示 ROI、轨迹、进入或离开原因及事件历史。在树莓派 Wayland 桌面会话下，运行 `sh scripts/run.sh` 可自动打开 Chromium。无桌面时可省略 `--preview`。临时用户服务通过 `sh scripts/start_service.sh` 启动，以 `systemctl --user stop edgevision-reproduction.service` 停止。

启用 MQTT 时，先准备 Mosquitto，核对配置中的主机和主题，运行检测时移除 `--no-mqtt`。另开终端运行 `mosquitto_sub -h 127.0.0.1 -t edgevision/alerts -v` 可观察消息。程序分别记录客户端接受发布和代理收到后返回的 QoS 1 确认。

## 为什么队列容量为 1

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

## 实测与复现

2026-11-18 在 Raspberry Pi 5 上用 320×320 模型、2 个 ORT 线程和请求 20 FPS 的 USB 摄像头运行 60 秒，关闭预览和 MQTT。采集和处理均为 **1,157 帧（19.28 FPS）**，应用队列替换 0 帧，软件端到端 p95 **43 ms**，模型 p95 **37 ms**。该次应用排队 p95 在 1 ms 分辨率下记为 0 ms。固定视频的三种模型输入对照中，前后 **391 个检测框及置信度逐项相同**。[本次实验数据](benchmarks/results/pi-release-20261118.json)

历史实机短测使用 Raspberry Pi 5 4GB、640×480 UVC、请求 30 FPS、320×320 模型和 2 个 ORT 线程。13.25 秒内实际采集 **28.38 FPS**，处理 **21.28 FPS**，应用队列替换 **24.7%**，软件端到端延迟 **p95 78 ms**。其他场景的帧率和延迟可通过相同命令重新测量。CPU/Vulkan 对照、模型输入尺寸与检测框差异见[实验记录](benchmarks/README.md)。[历史相机原始 JSON](benchmarks/results/optimized-camera.json)

要复现 320 模型，先下载素材，再运行 `.venv/bin/python -m pip install -e '.[model_tools]'` 和 `.venv/bin/python scripts/build_fast_model.py --size 320`，然后将本地配置的 `model.path` 改为 `models/yolox_nano_320.onnx`。原始模型及派生权重的来源和校验值见[模型清单](models/manifest.json)。

```bash
.venv/bin/python -m pytest -q -rs
.venv/bin/edgevision model-manifest
```

事件级 Precision、Recall 和 F1 需要独立人工标注的片段。历史短测也无法回答数小时连续运行或物理 USB 拔插后的表现。

## 继续阅读

- [工程解读](PROJECT_GUIDE.md) 涵盖输入、推理、跟踪、事件落盘和部署。
- [学习路线](LEARNING_PATH.md) 将源码和对应测试配对，[学习资源](KNOWLEDGE_AND_BILIBILI.md) 按知识点整理。
- [数据说明](data/README.md) 说明公开样例和现场证据的位置。[运行目录约束](SAFETY.md) 说明写入和清理边界。
