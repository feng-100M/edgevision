# 技术参考索引

按模块列出实现涉及的技术主题、仓库内的查阅位置和补充资料。视频链接指向哔哩哔哩对应主题的检索结果。实现细节与验证用例见[模块与测试索引](modules.md)。

## 运行环境与工具

| 技术主题 | 项目位置 | 视频检索 |
| --- | --- | --- |
| Linux 文件、权限和路径 | `README.md`、`SAFETY.md`、`scripts/setup.sh` | [Linux 命令行 入门](<https://search.bilibili.com/all?keyword=Linux%20%E5%91%BD%E4%BB%A4%E8%A1%8C%20%E5%85%A5%E9%97%A8>) |
| Shell 脚本 | `scripts/run.sh`、`scripts/start_service.sh` | [Shell 脚本 教程](<https://search.bilibili.com/all?keyword=Shell%20%E8%84%9A%E6%9C%AC%20%E6%95%99%E7%A8%8B>) |
| Python 基础与包 | `pyproject.toml`、`cli.py` | [Python 基础教程](<https://search.bilibili.com/all?keyword=Python%20%E5%9F%BA%E7%A1%80%20%E6%95%99%E7%A8%8B>) |
| Git 基础 | Git 提交历史 | [Git 入门教程](<https://search.bilibili.com/all?keyword=Git%20%E5%85%A5%E9%97%A8%20%E6%95%99%E7%A8%8B>) |

## 图像处理与模型推理

| 技术主题 | 项目位置 | 视频检索 |
| --- | --- | --- |
| OpenCV 图像与视频 | `sources.py`、`cli.py`、`preview.py` | [OpenCV Python 图像处理](<https://search.bilibili.com/all?keyword=OpenCV%20Python%20%E5%9B%BE%E5%83%8F%E5%A4%84%E7%90%86>) |
| 图像坐标与 ROI | `geometry.py`、`pipeline.py` | [OpenCV 多边形 ROI](<https://search.bilibili.com/all?keyword=OpenCV%20%E5%A4%9A%E8%BE%B9%E5%BD%A2%20ROI>) |
| 边界框、IoU 和 NMS | `geometry.py`、`detector.py` | [目标检测 IoU NMS 非极大值抑制](<https://search.bilibili.com/all?keyword=%E7%9B%AE%E6%A0%87%E6%A3%80%E6%B5%8B%20IoU%20NMS%20%E9%9D%9E%E6%9E%81%E5%A4%A7%E5%80%BC%E6%8A%91%E5%88%B6>) |
| YOLOX 输出解码 | `detector.py` 的 `postprocess()` | [YOLOX 原理 输出解码](<https://search.bilibili.com/all?keyword=YOLOX%20%E5%8E%9F%E7%90%86%20%E8%BE%93%E5%87%BA%E8%A7%A3%E7%A0%81>) |
| ONNX 与 ONNX Runtime | `detector.py`、`models/manifest.json` | [ONNX Runtime Python 推理](<https://search.bilibili.com/all?keyword=ONNX%20Runtime%20Python%20%E6%8E%A8%E7%90%86>) |
| 模型文件与 SHA-256 | `assets.py`、`models/manifest.json` | [SHA256 文件校验](<https://search.bilibili.com/all?keyword=SHA256%20%E6%96%87%E4%BB%B6%E6%A0%A1%E9%AA%8C>) |

## 轨迹关联与事件判定

| 技术主题 | 项目位置 | 视频检索 |
| --- | --- | --- |
| 多目标跟踪基本概念 | `tracker.py` | [目标跟踪 SORT DeepSORT](<https://search.bilibili.com/all?keyword=%E7%9B%AE%E6%A0%87%E8%B7%9F%E8%B8%AA%20SORT%20DeepSORT>) |
| 质心匹配与贪心分配 | `tracker.py`、`tests/test_tracker.py` | [多目标跟踪 IoU 匹配](<https://search.bilibili.com/all?keyword=%E5%A4%9A%E7%9B%AE%E6%A0%87%E8%B7%9F%E8%B8%AA%20IoU%20%E5%8C%B9%E9%85%8D>) |
| 有限状态机 | `events.py`、`tests/test_events.py` | [有限状态机 FSM 教程](<https://search.bilibili.com/all?keyword=%E6%9C%89%E9%99%90%E7%8A%B6%E6%80%81%E6%9C%BA%20FSM%20%E6%95%99%E7%A8%8B>) |
| 冷却、防抖和事件评测 | `events.py`、`evaluation.py` | [Precision Recall F1 目标检测评估](<https://search.bilibili.com/all?keyword=Precision%20Recall%20F1%20%E7%9B%AE%E6%A0%87%E6%A3%80%E6%B5%8B%E8%AF%84%E4%BC%B0>) |

## 并发、设备与消息传输

| 技术主题 | 项目位置 | 视频检索 |
| --- | --- | --- |
| Python threading 和 Condition | `frame_queue.py`、`pipeline.py` | [Python 多线程 Condition Queue](<https://search.bilibili.com/all?keyword=Python%20%E5%A4%9A%E7%BA%BF%E7%A8%8B%20Condition%20Queue>) |
| multiprocessing 与进程隔离 | `sources.py` | [Python multiprocessing 进程间通信](<https://search.bilibili.com/all?keyword=Python%20multiprocessing%20%E8%BF%9B%E7%A8%8B%E9%97%B4%E9%80%9A%E4%BF%A1>) |
| MQTT 发布订阅 | `mqtt_client.py`、Mosquitto 命令 | [MQTT Mosquitto 教程](<https://search.bilibili.com/all?keyword=MQTT%20Mosquitto%20%E6%95%99%E7%A8%8B>) |
| systemd 服务 | `scripts/start_service.sh`、`systemd/` | [Linux systemd 服务教程](<https://search.bilibili.com/all?keyword=Linux%20systemd%20%E6%9C%8D%E5%8A%A1%20%E6%95%99%E7%A8%8B>) |
| V4L2/UVC | `sources.py`、README 的摄像头检查 | [V4L2 USB 摄像头 Linux](<https://search.bilibili.com/all?keyword=V4L2%20USB%20%E6%91%84%E5%83%8F%E5%A4%B4%20Linux>) |

## 测试与性能分析

| 技术主题 | 项目位置 | 视频检索 |
| --- | --- | --- |
| pytest 测试设计 | `tests/` | [pytest 教程](<https://search.bilibili.com/all?keyword=pytest%20%E6%95%99%E7%A8%8B>) |
| 日志和故障注入 | `pipeline.py`、`scripts/`、`SAFETY.md` | [Python logging 日志教程](<https://search.bilibili.com/all?keyword=Python%20logging%20%E6%97%A5%E5%BF%97%E6%95%99%E7%A8%8B>) |
| FPS、p50/p95 和帧龄 | `metrics.py`、`benchmarks/` | [性能测试 p95 延迟 FPS](<https://search.bilibili.com/all?keyword=%E6%80%A7%E8%83%BD%E6%B5%8B%E8%AF%95%20p95%20%E5%BB%B6%E8%BF%9C%20FPS>) |
| psutil 与树莓派健康 | `metrics.py`、`benchmarks/results/` | [树莓派5 性能监控 温度 降频](<https://search.bilibili.com/all?keyword=%E6%A0%91%E8%8E%93%E6%B4%BE5%20%E6%80%A7%E8%83%BD%E7%9B%91%E6%8E%A7%20%E6%B8%A9%E5%BA%A6%20%E9%99%8D%E9%A2%91>) |
| 实验设计与可复现性 | `benchmarks/README.md`、`evaluation.py` | [机器学习 实验设计 可复现性](<https://search.bilibili.com/all?keyword=%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0%20%E5%AE%9E%E9%AA%8C%E8%AE%BE%E8%AE%A1%20%E5%8F%AF%E5%A4%8D%E7%8E%B0%E6%80%A7>) |
