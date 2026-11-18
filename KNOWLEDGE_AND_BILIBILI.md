# 需要补充的知识点与 B 站学习入口

下面的 B 站链接使用搜索入口和明确检索词，打开后优先选择近期、播放量稳定、能配合练习的系列。不要为了“看完视频”而看视频：每一项都要回到项目文件或命令上验证。

## A. 先学：Linux、Python 和 Git 基础

| 知识点                 | 需要掌握到的程度                                                                                 | 回到项目哪里练习                                   | B 站视频检索                                                                                                           |
| ---------------------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Linux 文件、权限和路径 | 会用 `pwd`、`ls`、`cd`、`cp`、`mv`、`chmod`、相对/绝对路径；知道进程对文件权限的影响 | `README.md`、`SAFETY.md`、`scripts/setup.sh` | [Linux 命令行 入门](<https://search.bilibili.com/all?keyword=Linux%20%E5%91%BD%E4%BB%A4%E8%A1%8C%20%E5%85%A5%E9%97%A8>) |
| Shell 脚本             | 能读懂 `set -eu`、变量、退出码、`trap`、管道和条件判断                                       | `scripts/run.sh`、`scripts/start_service.sh`   | [Shell 脚本 教程](<https://search.bilibili.com/all?keyword=Shell%20%E8%84%9A%E6%9C%AC%20%E6%95%99%E7%A8%8B>)            |
| Python 基础与包        | 会读函数、类、异常、迭代器、模块导入和虚拟环境                                                   | `pyproject.toml`、`cli.py`                     | [Python 基础教程](<https://search.bilibili.com/all?keyword=Python%20%E5%9F%BA%E7%A1%80%20%E6%95%99%E7%A8%8B>)           |
| Git 基础               | 会看 `status`、`diff`、提交记录，理解工作区和索引                                            | 整个项目的变更检查                                 | [Git 入门教程](<https://search.bilibili.com/all?keyword=Git%20%E5%85%A5%E9%97%A8%20%E6%95%99%E7%A8%8B>)                 |

### B. 边读代码边学：图像处理和模型推理

| 知识点               | 需要掌握到的程度                                               | 回到项目哪里练习                           | B 站视频检索                                                                                                                                                                        |
| -------------------- | -------------------------------------------------------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OpenCV 图像与视频    | 理解 BGR、`numpy` 数组的 H/W/C、`VideoCapture`、编码和写盘 | `sources.py`、`cli.py`、`preview.py` | [OpenCV Python 图像处理](<https://search.bilibili.com/all?keyword=OpenCV%20Python%20%E5%9B%BE%E5%83%8F%E5%A4%84%E7%90%86>)                                                           |
| 图像坐标与 ROI       | 能把归一化坐标换成像素坐标，理解边界、旋转和镜像顺序           | `geometry.py`、`pipeline.py`           | [OpenCV 多边形 ROI](<https://search.bilibili.com/all?keyword=OpenCV%20%E5%A4%9A%E8%BE%B9%E5%BD%A2%20ROI>)                                                                            |
| 边界框、IoU 和 NMS   | 能手算 IoU，解释 NMS 为什么去重，知道置信度阈值不是准确率      | `geometry.py`、`detector.py`           | [目标检测 IoU NMS 非极大值抑制](<https://search.bilibili.com/all?keyword=%E7%9B%AE%E6%A0%87%E6%A3%80%E6%B5%8B%20IoU%20NMS%20%E9%9D%9E%E6%9E%81%E5%A4%A7%E5%80%BC%E6%8A%91%E5%88%B6>) |
| YOLOX 输出解码       | 能解释 stride 网格、中心点/宽高解码、objectness × 类别概率    | `detector.py` 的 `postprocess()`       | [YOLOX 原理 输出解码](<https://search.bilibili.com/all?keyword=YOLOX%20%E5%8E%9F%E7%90%86%20%E8%BE%93%E5%87%BA%E8%A7%A3%E7%A0%81>)                                                   |
| ONNX 与 ONNX Runtime | 能查看模型输入输出、固定尺寸、CPU provider 和线程数            | `detector.py`、`models/manifest.json`  | [ONNX Runtime Python 推理](<https://search.bilibili.com/all?keyword=ONNX%20Runtime%20Python%20%E6%8E%A8%E7%90%86>)                                                                   |
| 模型文件与 SHA-256   | 能用哈希判断模型是否被替换，并理解许可证和来源记录             | `assets.py`、`models/manifest.json`    | [SHA256 文件校验](<https://search.bilibili.com/all?keyword=SHA256%20%E6%96%87%E4%BB%B6%E6%A0%A1%E9%AA%8C>)                                                                           |

## C. 边读代码边学：跟踪和事件语义

| 知识点               | 需要掌握到的程度                             | 回到项目哪里练习                          | B 站视频检索                                                                                                                                                  |
| -------------------- | -------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 多目标跟踪基本概念   | 区分检测框、轨迹 ID、漏检、遮挡和轨迹过期    | `tracker.py`                            | [目标跟踪 SORT DeepSORT](<https://search.bilibili.com/all?keyword=%E7%9B%AE%E6%A0%87%E8%B7%9F%E8%B8%AA%20SORT%20DeepSORT>)                                     |
| 质心匹配与贪心分配   | 能解释候选代价、阈值、同一轨迹不能重复占用   | `tracker.py`、`tests/test_tracker.py` | [多目标跟踪 IoU 匹配](<https://search.bilibili.com/all?keyword=%E5%A4%9A%E7%9B%AE%E6%A0%87%E8%B7%9F%E8%B8%AA%20IoU%20%E5%8C%B9%E9%85%8D>)                      |
| 有限状态机           | 能把“区域外/区域内/暂时丢失”写成状态和转移 | `events.py`、`tests/test_events.py`   | [有限状态机 FSM 教程](<https://search.bilibili.com/all?keyword=%E6%9C%89%E9%99%90%E7%8A%B6%E6%80%81%E6%9C%BA%20FSM%20%E6%95%99%E7%A8%8B>)                      |
| 冷却、防抖和事件评测 | 能区分重复告警、漏报、误报和事件级 F1        | `events.py`、`evaluation.py`          | [Precision Recall F1 目标检测评估](<https://search.bilibili.com/all?keyword=Precision%20Recall%20F1%20%E7%9B%AE%E6%A0%87%E6%A3%80%E6%B5%8B%E8%AF%84%E4%BC%B0>) |

## D. 进阶：并发、系统和消息系统

| 知识点                        | 需要掌握到的程度                                                 | 回到项目哪里练习                           | B 站视频检索                                                                                                                                           |
| ----------------------------- | ---------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Python threading 和 Condition | 能读懂生产者/消费者、关闭唤醒、超时和单调时钟                    | `frame_queue.py`、`pipeline.py`        | [Python 多线程 Condition Queue](<https://search.bilibili.com/all?keyword=Python%20%E5%A4%9A%E7%BA%BF%E7%A8%8B%20Condition%20Queue>)                     |
| multiprocessing 与进程隔离    | 能解释为什么 UVC 读帧放在子进程，以及如何终止/重连               | `sources.py`                             | [Python multiprocessing 进程间通信](<https://search.bilibili.com/all?keyword=Python%20multiprocessing%20%E8%BF%9B%E7%A8%8B%E9%97%B4%E9%80%9A%E4%BF%A1>) |
| MQTT 发布订阅                 | 能理解 topic、QoS、retain、重连和发布失败                        | `mqtt_client.py`、Mosquitto 命令         | [MQTT Mosquitto 教程](<https://search.bilibili.com/all?keyword=MQTT%20Mosquitto%20%E6%95%99%E7%A8%8B>)                                                  |
| systemd 服务                  | 能读 unit、Restart、日志和资源限制，知道用户服务与系统服务的区别 | `scripts/start_service.sh`、`systemd/` | [Linux systemd 服务教程](<https://search.bilibili.com/all?keyword=Linux%20systemd%20%E6%9C%8D%E5%8A%A1%20%E6%95%99%E7%A8%8B>)                           |
| V4L2/UVC                      | 能枚举 `/dev/video*`、查看格式、理解驱动缓冲和重连             | `sources.py`、README 的摄像头检查        | [V4L2 USB 摄像头 Linux](<https://search.bilibili.com/all?keyword=V4L2%20USB%20%E6%91%84%E5%83%8F%E5%A4%B4%20Linux>)                                     |

## E. 工程质量和性能分析

| 知识点              | 需要掌握到的程度                                                     | 回到项目哪里练习                             | B 站视频检索                                                                                                                                                                              |
| ------------------- | -------------------------------------------------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| pytest 测试设计     | 能读 fixture、参数化、模拟依赖和边界测试；知道测试行为而不是复制实现 | `tests/`                                   | [pytest 教程](<https://search.bilibili.com/all?keyword=pytest%20%E6%95%99%E7%A8%8B>)                                                                                                       |
| 日志和故障注入      | 能用日志定位输入、模型、存储、MQTT 和服务退出问题                    | `pipeline.py`、`scripts/`、`SAFETY.md` | [Python logging 日志教程](<https://search.bilibili.com/all?keyword=Python%20logging%20%E6%97%A5%E5%BF%97%E6%95%99%E7%A8%8B>)                                                               |
| FPS、p50/p95 和帧龄 | 能区分采集、推理、端到端延迟，理解分位数比平均值更能发现长尾         | `metrics.py`、`benchmarks/`              | [性能测试 p95 延迟 FPS](<https://search.bilibili.com/all?keyword=%E6%80%A7%E8%83%BD%E6%B5%8B%E8%AF%95%20p95%20%E5%BB%B6%E8%BF%9C%20FPS>)                                                   |
| psutil 与树莓派健康 | 能读取 RSS、CPU、温度、swap、降频并保存原始结果                      | `metrics.py`、`benchmarks/results/`      | [树莓派5 性能监控 温度 降频](<https://search.bilibili.com/all?keyword=%E6%A0%91%E8%8E%93%E6%B4%BE5%20%E6%80%A7%E8%83%BD%E7%9B%91%E6%8E%A7%20%E6%B8%A9%E5%BA%A6%20%E9%99%8D%E9%A2%91>)      |
| 实验设计与可复现性  | 能固定模型、输入尺寸、线程数和视频片段，只改一个变量并记录限制       | `benchmarks/README.md`、`evaluation.py`  | [机器学习 实验设计 可复现性](<https://search.bilibili.com/all?keyword=%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0%20%E5%AE%9E%E9%AA%8C%E8%AE%BE%E8%AE%A1%20%E5%8F%AF%E5%A4%8D%E7%8E%B0%E6%80%A7>) |

## 推荐观看顺序

1. Linux 命令行、Shell、Python 基础和 Git。
2. OpenCV 图像/视频、坐标、ROI、IoU/NMS。
3. YOLOX、ONNX Runtime 和模型文件校验。
4. SORT/DeepSORT 的跟踪概念，再回到项目的轻量匹配器。
5. Python 线程/进程、队列和 MQTT。
6. systemd、pytest、性能指标和实验设计。

每看完一组视频，立即完成 [LEARNING_PATH.md](LEARNING_PATH.md) 对应阶段的练习；如果无法用项目中的一个命令或测试验证，就说明知识还停留在术语层面。
