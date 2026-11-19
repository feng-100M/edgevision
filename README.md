# EdgeVision

EdgeVision 在 Raspberry Pi 5 上使用 USB 摄像头检测人员进出指定区域。设备在本地完成 YOLOX-Nano 推理、轨迹关联和区域判定，生成带时间戳的事件记录、现场截图和可选的 MQTT 告警。

[v0.2.0 版本说明与树莓派验收结果](CHANGELOG.md)

## 工程亮点

- **优先处理最新画面。** 摄像头在独立进程中读取。推理忙时，采集线程用新帧替换仍在等待的旧帧，避免告警持续落后于现场。逐帧分析录像时可切换到同步回放。
- **为 ARM CPU 精简后处理。** 复用同一输入尺寸的解码网格，先按人员置信度筛选候选框，再比较类别。树莓派上，320×320 模型的后处理中位耗时从 **0.703 ms 降至 0.222 ms**。在三种输入尺寸的固定视频对照中，优化前后的 391 个检测框及置信度逐项一致。
- **按轨迹生成区域事件。** 系统跟踪人员检测框的底边中点。轨迹进入或离开多边形区域时生成对应事件，持续停留和短暂漏检由状态机处理，减少重复告警。
- **先保存事件，再处理截图和告警。** 检测线程将事件 ID 和待发状态写入 JSONL，后台线程负责保存 JPEG 和发送 MQTT 消息。即使截图队列已满，已保存的事件仍可在代理恢复后补发。

## 树莓派实测

Raspberry Pi 5（4 GB），640×480 UVC 摄像头，请求 20 FPS，YOLOX-Nano 320×320，ONNX Runtime 使用 2 个推理线程。连续运行 60 秒，关闭预览和 MQTT，使用全画面检测。

| 处理帧率 | 软件端到端延迟 p95 | 模型推理耗时 p95 | 应用队列替换帧数 |
| ---: | ---: | ---: | ---: |
| **19.19 FPS**（1,152 帧） | **41 ms** | **35 ms** | **3** |

软件端到端延迟从摄像头读帧完成计至该帧检测处理完成。其他工况、模型尺寸和 CPU/Vulkan 对照见[性能实验](benchmarks/README.md)。[本次实测 JSON](benchmarks/results/pi-release-20261119.json)

## 快速开始

使用公开视频即可验证完整事件链路。以下命令适用于安装了 Python 3.11 或 3.12 及 venv 的 Linux 环境。首次运行需联网下载依赖、模型和样例；素材会按 SHA-256 校验。

```bash
git clone https://github.com/feng-100M/edgevision.git
cd edgevision
sh scripts/setup.sh
.venv/bin/edgevision assets
.venv/bin/edgevision replay --frames 100 --mode sync --no-mqtt
```

终端的 `processed_frames` 应为 100。`output/YYYY-MM-DD/events.jsonl` 记录区域事件，`snapshot_path` 指向对应截图。示例配置使用官方 416×416 模型；复现实测中的 320×320 配置见[运行指南](docs/runtime.md)。

## 摄像头与实时预览

在**连接摄像头的树莓派**上执行下列命令。首次配置时，将 `input.device` 设为实际设备节点，并按现场画面调整 `roi.points`。使用 Ctrl+C 结束检测。

```bash
cp -n config.example.yaml config.local.yaml
.venv/bin/edgevision check --config config.local.yaml --input uvc --duration 5
.venv/bin/edgevision run --config config.local.yaml --input uvc --preview --no-mqtt
```

**在树莓派桌面查看**，打开启动日志中 `Live preview` 后面的地址。上面的命令使用 EdgeVision 默认端口 `8765`，对应 `http://127.0.0.1:8765/`。如果该端口已被占用，可在上述 `edgevision run` 命令末尾加上 `--preview-port 9000`，改用树莓派上空闲的 `9000` 端口。

**在笔记本查看**，保持树莓派上的检测程序运行，在笔记本终端建立 SSH 转发。两台设备的端口可以相同，也可以不同。下面以笔记本上的空闲端口 `18765`、树莓派上的默认预览端口 `8765` 为例。将 `YOUR_USER@PI_HOST` 替换为实际的树莓派 SSH 用户名和地址。

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18765:127.0.0.1:8765 YOUR_USER@PI_HOST
```

保持 SSH 连接，在笔记本浏览器打开 `http://127.0.0.1:18765/`。按自己的环境调整时：

| 哪一端的端口变了 | 需要同步修改的位置 |
| --- | --- |
| 笔记本的 `18765` 被占用 | 选一个笔记本上的空闲端口，替换 `-L` 左侧的 `18765` 和笔记本浏览器地址中的端口。 |
| 树莓派用 `--preview-port 9000` 启动 | 将 `-L` 右侧的 `8765` 改为 `9000`。笔记本浏览器仍使用左侧选定的端口。 |

## 文档

| 文档 | 内容 |
| --- | --- |
| [系统设计](PROJECT_GUIDE.md) | 采集、推理、跟踪和事件输出的数据流与设计取舍 |
| [运行指南](docs/runtime.md) | Windows 安装、模型选择、MQTT、systemd 与指标定义 |
| [模块与测试索引](docs/modules.md) | 源码入口、行为约定与回归测试 |
| [性能实验](benchmarks/README.md) | 实机配置、对照方法与原始记录 |
| [数据说明](data/README.md) · [存储边界](SAFETY.md) | 公开样例、现场证据与保留策略 |
