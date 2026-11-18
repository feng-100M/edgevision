# EdgeVision 数据说明

固定输入按拍摄片段保存，每个片段只能属于一个评测集合。相邻帧不得随机拆分，避免事件泄漏。

真实摄像头视频可能包含个人信息，只保存在项目内 `data/videos/`，不提交到仓库。摄像头截图同样只保存在项目内。流水线和事件规则的确定性验证使用 `tests/` 中的合成帧及检测序列。

运行产生的 `data/images/uvc-*`、`output/YYYY-MM-DD/*.jpg` 和对应 `events.jsonl` 属于现场证据，由部署者按保留策略管理。

公开固定输入由 `python -m edgevision.cli assets` 下载并核对 SHA-256：

- `data/videos/vtest.avi`：OpenCV 4.11.0 `samples/data/vtest.avi`，用于吞吐与回放测试。
- `data/images/basketball1.png`：OpenCV 4.11.0 `samples/data/basketball1.png`，用于单图推理检查。

固定下载地址和校验值在 `src/edgevision/assets.py` 中。这些是公开样例，不带本项目的独立事件标注，不能凭回放输出报告事件准确率。

事件标注采用 JSON 文件记录进入和离开时间窗口；没有帧级边界框标注时只计算事件级 Precision、Recall 和 F1，不报告 mAP。
