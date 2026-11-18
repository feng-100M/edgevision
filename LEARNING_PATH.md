# EdgeVision 学习路线

这份路线把项目按“先能解释数据，再能解释算法，最后能解释系统运行”的顺序拆开。每一阶段都先用固定视频和已有测试验证，最后再接入真实 UVC 摄像头。

## 0. 先建立全局地图

先读：

- [README.md](README.md) 的项目目标、运行命令和限制
- [PROJECT_GUIDE.md](PROJECT_GUIDE.md) 的数据流和模块职责
- [config.example.yaml](config.example.yaml) 的输入、模型、ROI、输出和 MQTT 字段

需要能回答：一帧图像从哪里来，经过哪些模块，什么条件会变成 `person_entered`，事件最终写到哪里、发到哪里。

建议画出这条链路：

```text
视频文件/UVC → Frame → 最新帧队列 → 方向校正 → Detector
    → Detection → Tracker → ROI 状态机 → Event
    → JPEG + JSONL + MQTT
```

阶段练习：不看源码，用自己的话解释为什么项目默认使用容量为 1 的队列，以及为什么 MQTT 故障不应该阻塞本地保存。

## 1. Python 环境、配置和数据对象

先读：

- [pyproject.toml](pyproject.toml)
- [src/edgevision/config.py](src/edgevision/config.py)
- [src/edgevision/types.py](src/edgevision/types.py)
- [tests/test_config.py](tests/test_config.py)

要掌握：虚拟环境、包入口、dataclass、类型注解、`Path`、异常边界、YAML 到 Python 对象的映射。重点理解 `load_config()` 为什么要把相对路径解析成绝对路径，以及为什么配置错误要在启动时失败。

阶段练习：复制 `config.example.yaml`，故意修改 `model.path`、ROI 点、`roi.enabled`、`input.min_sharpness`、MQTT topic 和旋转角度，运行配置测试并解释每条错误信息。

## 2. 图像坐标、ROI 和 IoU

先读：

- [src/edgevision/geometry.py](src/edgevision/geometry.py)
- [tests/test_geometry.py](tests/test_geometry.py)
- `pipeline.py` 中把归一化 ROI 转成像素坐标的部分

要掌握：图像坐标原点、`(x1, y1, x2, y2)` 框、底部中心点、射线法点在多边形内、边界算内部、IoU 和坐标裁剪。注意配置中的 ROI 是 `0..1` 归一化坐标，几何函数接收像素坐标。

阶段练习：画出一个矩形 ROI，分别测试脚在边界、区域内和区域外的检测框；再用两个框手算 IoU，与测试结果对照。

## 3. YOLOX 与 ONNX Runtime 推理

先读：

- [src/edgevision/detector.py](src/edgevision/detector.py)
- [tests/test_detector.py](tests/test_detector.py)
- [models/manifest.json](models/manifest.json)
- [models/YOLOX-LICENSE.txt](models/YOLOX-LICENSE.txt)

要掌握：BGR 与 RGB、`float32`、letterbox、固定输入尺寸、stride 网格、objectness × 类别概率、NMS、ONNX 输入输出和 SHA-256。这个适配器使用 YOLOX 的 BGR `0..255` 约定，不能直接套用其他 YOLO 教程的 `/255` 预处理。

阶段练习：先运行 `infer` 单图命令，再在 `postprocess()` 的模拟输出测试中跟踪一个框从网格坐标还原到原图坐标的过程；比较 416、352、320 输入尺寸的延迟和输出差异。

## 4. 轻量跟踪与事件状态机

先读：

- [src/edgevision/tracker.py](src/edgevision/tracker.py)
- [src/edgevision/events.py](src/edgevision/events.py)
- [tests/test_tracker.py](tests/test_tracker.py)
- [tests/test_events.py](tests/test_events.py)

要掌握：IoU/质心匹配、贪心一对一分配、轨迹 ID、漏检保留、单调时间、ROI 进入/离开状态、冷却窗口和状态过期。检测框是每帧结果，轨迹和事件才是跨帧语义。

阶段练习：手工构造“区域外→区域内→区域内→区域外”的四帧检测，预测轨迹 ID 和事件序列；再加入一帧漏检，解释为什么不应立即产生离开事件。

## 5. 视频输入、UVC 和最新帧队列

先读：

- [src/edgevision/sources.py](src/edgevision/sources.py)
- [src/edgevision/frame_queue.py](src/edgevision/frame_queue.py)
- [tests/test_frame_queue.py](tests/test_frame_queue.py)
- [tests/test_sources.py](tests/test_sources.py)

要掌握：OpenCV `VideoCapture`、媒体时间、单调时钟、生产者/消费者、`Condition`、队列关闭、丢帧统计、UVC 驱动阻塞、自动对焦预热和子进程重连。先用视频文件理解帧生命周期，再研究摄像头子进程为什么可以被单独终止。

阶段练习：运行固定视频回放，观察 `queue_dropped_frames` 和 `max_queue_wait_ms`；修改推理速度后说明为什么队列不会无限增长。

## 6. 本地存储、MQTT 和故障隔离

先读：

- [src/edgevision/storage.py](src/edgevision/storage.py)
- [src/edgevision/mqtt_client.py](src/edgevision/mqtt_client.py)
- [tests/test_storage.py](tests/test_storage.py)
- [tests/test_mqtt.py](tests/test_mqtt.py)
- [SAFETY.md](SAFETY.md)

要掌握：JSONL、原子替换、路径穿越防护、目录保留、磁盘配额、MQTT QoS 1、后台网络线程和“本地结果优先”。保存事件和发布消息是两个独立的副作用，Broker 不可用不能抹掉本地证据。

阶段练习：停止 Mosquitto 后运行回放，确认 JSONL 和截图仍然生成；恢复 Broker 后再验证发布；构造越界路径，确认 `StorageError` 阻止写入。

## 7. 指标、流水线、CLI 和预览

先读：

- [src/edgevision/metrics.py](src/edgevision/metrics.py)
- [src/edgevision/pipeline.py](src/edgevision/pipeline.py)
- [src/edgevision/cli.py](src/edgevision/cli.py)
- [src/edgevision/preview.py](src/edgevision/preview.py)
- [tests/test_pipeline.py](tests/test_pipeline.py)

要掌握：同步基线和 latest 模式的区别、单帧异常隔离、端到端延迟、模型计算耗时、RSS/温度/降频、CLI 子命令和 loopback MJPEG。`capture_fps`、`inference_fps`、`model_compute_fps` 的定义不同，不能只看一个数字。

阶段练习：分别运行 `infer`、`check`、`replay`，再运行带 `--preview` 的 `run`；把一次结果 JSON 中的 `capture_fps`、`inference_fps`、`model_compute_fps`、`queue_drop_rate`、`end_to_end_p95_ms`、`event_output_p95_ms`、`focus_score_min` 和 `peak_temperature_c` 用自己的话解释一遍。

## 8. systemd、故障注入和评测

先读：

- [scripts/start_service.sh](scripts/start_service.sh)
- [systemd/edgevision.service](systemd/edgevision.service)
- [scripts/setup.sh](scripts/setup.sh)
- [benchmarks/README.md](benchmarks/README.md)
- [src/edgevision/evaluation.py](src/edgevision/evaluation.py)

要掌握：用户级 systemd、Restart 策略、日志、资源限制、故障注入、事件级 TP/FP/FN、Precision/Recall/F1、基线与对照实验。没有帧级标注时，只能报告事件级指标，不能把结果叫作 mAP。

阶段练习：先对合成视频做基线，再改变输入尺寸、请求 FPS 或线程数做单变量对照；保存原始 JSON/CSV，并写出“变化—指标—解释—限制”四句话。简历只写实测值，不把单帧置信度写成准确率。

## 9. 最后接入真实 UVC

完成前面所有离线练习后，再按 README 的顺序执行 `v4l2-ctl` 枚举、`check --input uvc` 和短时 `run`。先确认设备节点、分辨率、方向和 ROI，再进行 MQTT 和长期运行测试。

阶段验收：能解释一次真实运行中的采集 FPS、推理 FPS、帧龄、丢帧、RSS、温度、重连次数和事件延迟；能从 JSONL、日志和截图定位一次故障。

## 10. 推荐的最小练习顺序

1. 通过配置和几何测试。
2. 用一张图跑通 `infer`。
3. 用固定视频跑通 `replay --no-mqtt`。
4. 修改 ROI，观察进入/离开事件。
5. 停止 MQTT，确认本地落盘仍工作。
6. 比较 `sync` 与 `latest` 的吞吐和帧龄。
7. 打开本地预览，解释每个叠加元素。
8. 最后才连接真实摄像头并做健康检查。
