# EdgeVision 数据说明

固定输入按拍摄片段保存，每个片段只能属于一个评测集合。相邻帧不得随机拆分，避免事件泄漏。

真实摄像头视频可能包含个人信息，只保存在项目内 `data/videos/`，不提交到仓库。摄像头截图同样只保存在项目内。流水线和事件规则的确定性验证使用 `tests/` 中的合成帧及检测序列。

运行产生的 `data/images/uvc-*`、`output/YYYY-MM-DD/*.jpg` 和对应 `events.jsonl` 属于现场证据，由部署者按保留策略管理。

公开固定输入由 `python -m edgevision.cli assets` 下载并核对 SHA-256：

- `data/videos/vtest.avi`：OpenCV 4.11.0 `samples/data/vtest.avi`，用于吞吐与回放测试。
- `data/images/basketball1.png`：OpenCV 4.11.0 `samples/data/basketball1.png`，用于单图推理检查。

固定下载地址和校验值在 `src/edgevision/assets.py` 中。这些是公开样例，不带本项目的独立事件标注，不能凭回放输出报告事件准确率。

## 评估区域进入和离开

每个独立拍摄片段使用唯一标识。预测 JSONL 和标注 JSON 中的事件均可用 `clip_id` 指定标识，省略时取原始 `source_name`。回放写入的 `source_name` 是文件路径，两侧应逐字一致。时间以片段起点为零，单位为秒。有效时长取自完整的标注区间，包含零事件片段。若一段录像中途缺少有效标注，将有效区间分成独立片段后分别回放。

```json
{
  "clip_seconds": {"front-door-day": 30, "front-door-night": 45},
  "events": [
    {"clip_id": "front-door-day", "source_time": 4.2, "event_type": "person_entered", "roi_name": "restricted"},
    {"clip_id": "front-door-day", "source_time": 7.1, "event_type": "person_left", "roi_name": "restricted"}
  ]
}
```

```bash
.venv/bin/edgevision evaluate --annotations annotations.json --predicted day.jsonl night.jsonl --window 1
```

一条预测最多匹配同片段、同区域、同类型的一次真实事件。报告按进入、离开列出人工标注数、命中、误报和漏报，并给出总有效时长。按夜间、遮挡等场景评测时，对每个场景分别提供其片段标注和预测文件。
