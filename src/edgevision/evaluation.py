"""把预测事件与独立标注按时间窗口做最大基数匹配。

这里评估的是进入/离开事件的 Precision、Recall 和 F1，不把没有帧级框标注
的回放误报成 mAP；匹配算法允许后面的预测重新占用更合适的真值事件。

评测输入是已经生成的事件记录，而不是检测框序列。先按事件类型、ROI 和时间
窗口建立可匹配关系，再做最大基数匹配，最后统计 TP/FP/FN，因此重复告警不会被算成新的真阳性。
"""


def evaluate_events(predicted, truth, window_seconds=1.):
    """返回 TP/FP/FN、重复告警和事件级 Precision/Recall/F1。"""
    # 评测边界只允许非负时间窗口；没有帧级标注时不提供 mAP 等框级指标。
    if window_seconds < 0:
        raise ValueError("window_seconds must be nonnegative")
    # 为每条预测建立候选真值列表，并按时间差排序保证结果确定。
    adjacency = {}
    for i, p in enumerate(predicted):
        candidates = []
        for j, t in enumerate(truth):
            delta = abs(p["source_time"] - t["source_time"])
            if p["event_type"] == t["event_type"] and p["roi_name"] == t["roi_name"] and delta <= window_seconds:
                candidates.append((delta, j))
        adjacency[i] = [j for _, j in sorted(candidates)]
    # 增广路径式分配允许后来的预测重新占用真值，得到最大数量的合法匹配。
    matched_truth = {}

    def assign(i, seen):
        for j in adjacency[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in matched_truth or assign(matched_truth[j], seen):
                matched_truth[j] = i
                return True
        return False
    for i in sorted(adjacency, key=lambda i: (predicted[i]["source_time"], i)):
        assign(i, set())
    # 未匹配预测是 FP，未匹配真值是 FN；命中同一真值的额外预测单独计为 duplicates。
    used_p = set(matched_truth.values())
    used_t = set(matched_truth)
    duplicates = sum(
        i not in used_p and any(
            j in used_t for j in adjacency[i]) for i in adjacency)
    tp = len(used_p)
    fp = len(predicted) - tp
    fn = len(truth) - tp
    precision = tp / (tp + fp) if tp + fp else 0.
    recall = tp / (tp + fn) if tp + fn else 0.
    return {"tp": tp,
            "fp": fp,
            "fn": fn,
            "duplicates": duplicates,
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.,
            "window_seconds": window_seconds,
            "matching": "maximum cardinality; deterministic nearest-compatible reassignment"}
