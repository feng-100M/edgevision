# 模块与测试索引

实时检测和视频回放共用推理、跟踪与告警逻辑。下表按一帧画面经过系统的顺序列出实现入口，以及可以独立验证的行为。

| 模块 | 实现 | 验证内容 |
| --- | --- | --- |
| 配置与数据对象 | [配置解析](../src/edgevision/config.py) · [数据类型](../src/edgevision/types.py) | [配置测试](../tests/test_config.py) 覆盖相对路径、旋转角度和 ROI 参数。 |
| 输入与帧交接 | [视频与 UVC 输入](../src/edgevision/sources.py) · [最新帧队列](../src/edgevision/frame_queue.py) | [输入测试](../tests/test_sources.py) 核对回放时间与方向校正。[队列测试](../tests/test_frame_queue.py) 核对旧帧替换、关闭唤醒和排队时间。 |
| 模型推理 | [YOLOX 适配器](../src/edgevision/detector.py) · [模型清单](../models/manifest.json) | [检测测试](../tests/test_detector.py) 覆盖 BGR 预处理、网格解码、类别筛选和 NMS。 |
| 区域事件 | [几何计算](../src/edgevision/geometry.py) · [跟踪器](../src/edgevision/tracker.py) · [事件状态机](../src/edgevision/events.py) | [跟踪测试](../tests/test_tracker.py) 核对轨迹关联，[事件测试](../tests/test_events.py) 核对进入、离开及冷却期。 |
| 本地记录与消息 | [事件存储](../src/edgevision/storage.py) · [MQTT 发布](../src/edgevision/mqtt_client.py) | [存储测试](../tests/test_storage.py) 覆盖空间配额与截图一致性，[MQTT 测试](../tests/test_mqtt.py) 区分发布请求与代理确认。 |
| 流水线与预览 | [运行编排](../src/edgevision/pipeline.py) · [运行指标](../src/edgevision/metrics.py) · [预览服务](../src/edgevision/preview.py) | [流水线测试](../tests/test_pipeline.py) 验证协作与退出，[预览测试](../tests/test_preview.py) 验证 HTTP 服务。 |

从仓库根目录可单独运行队列与流水线测试。

```bash
.venv/bin/python -m pytest -q tests/test_frame_queue.py tests/test_pipeline.py
```

相关技术主题、对应实现及中文视频检索入口见[技术参考索引](references.md)。
