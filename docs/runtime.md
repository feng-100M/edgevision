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

启用 MQTT 时，先准备 Mosquitto，核对配置中的主机和主题，运行检测时移除 `--no-mqtt`。另开终端运行 `mosquitto_sub -h 127.0.0.1 -t edgevision/alerts -v` 可观察消息。服务先把事件 ID 写入本地 JSONL。启用 MQTT 时，同一条记录含 `delivery_state=pending`。连接恢复或检测进程重启后，后台发布器会继续发送，即使摄像头还没产生新帧。告警可先于截图送达，收到消息后可按同一事件 ID 查本地历史截图。收到 QoS 1 PUBACK 后才将记录更新为 `acked`。旧版记录和关闭 MQTT 时产生的记录不参与补发。

值班端在自己的配置中设置代理地址和告警主题，使用以下命令保存去重收件记录。每台值班机使用固定且唯一的客户端 ID。应在开始检测前订阅，离线期间的收件依赖代理保留该订阅的持久会话。代理重启后要保留会话及离线消息，需开启代理自己的持久化。代理确认后的告警可用 `receipts.event_id` 核对到站情况。

```bash
.venv/bin/edgevision receive --config config.local.yaml --client-id duty-01 --db diagnostics/receipts.sqlite3
mosquitto_sub -h 127.0.0.1 -t 'edgevision/alerts/health' -v
```

健康主题为配置的告警主题加 `/health`。相机读取超时或处理失败会上报 `unavailable`，下一张成功处理的新画面上报 `recovered`。健康消息保留最新值，运行期间约每 5 秒刷新。关注 `last_success_at`、`consecutive_failures` 和 `last_recovery_at`；预览的 `/status` 也提供这些字段。正常结束上报 `stopped`，代理发现客户端异常掉线时发布遗嘱 `offline`。

服务默认关闭逐帧 CSV。需要诊断时运行 `sh scripts/start_service.sh --trace diagnostics/service-frames.csv`。每个路径使用当前 CSV 和一个 `.1` 备份，每个文件上限 4 MiB，每段都带表头。历史版本遗留的 `output/service-frames.csv` 保留原文件并从事件逻辑配额中排除；它仍占用实际磁盘空间。

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
| 推理循环 → 事件存储与截图线程 | 同步持久化事件元数据。磁盘繁忙时该步骤可能延长处理时间。有界 FIFO 只排队截图，队满时计入 `output_queue_dropped`，事件 ID 和待发状态已落盘。 |

例如推理正在处理 A，B 和 C 先后到达应用队列，C 会替换 B。A 完成后直接取 C。队列为空时消费者睡眠等帧。容量 1 限制应用层积压，对短时目标的覆盖率取决于实际处理频率。要逐帧复核录像，可用 `replay --mode sync`。摄像头的驱动缓冲、跨进程传输和一次模型计算仍会贡献延迟。

| 运行指标 | 实际测量范围 |
| --- | --- |
| `camera_ipc_skipped_frames` | 同次相机子进程读取序号在主进程出现的缺口。只统计到已收到的帧，无法测量传感器漏采。保留旧字段 `camera_driver_dropped_frames`。 |
| `queue_dropped_frames`、`queue_drop_rate` | 应用线程队列替换的帧数，比例以交到主进程流水线的帧数为分母。 |
| `app_queue_wait_p95_ms` | 已取出帧从应用入队到出队的 p95。同步模式或无样本时为 `null`。 |
| `max_queue_wait_ms`、`end_to_end_p95_ms` | 前者是历史命名，记录软件读帧完成到应用出队的最大帧龄。后者记录读帧完成到检测处理完成的 p95。均不含曝光时间。 |
| `events`、`events_persisted`、`events_dropped` | 本次生成、成功保存和因存储失败丢失的事件数。未确认记录受配额清理保护，积压占满空间后新事件会报告保存失败。 |
| `mqtt_acknowledged`、`mqtt_outbox_pending` | 本次收到的 PUBACK 数（可能包含上次运行的积压）与磁盘上尚待确认的事件数。 |
| `output_queue_dropped`、`snapshot_skipped` | 截图队满次数，以及因模糊、队满、配额或写入失败等原因未产出截图的次数。 |
| `storage_failed`、`mqtt_failed` | 事件持久化失败次数、MQTT 发布尝试或确认失败次数。断线等待重试的记录计入磁盘待发量。 |
