"""有界事件存储；清理只触碰本模块创建的 JSONL 和截图。

保存事件时先写临时文件并原子替换，再按日期、容量和剩余空间清理旧记录，
这样进程被终止时不会留下半行 JSON 或半张 JPEG。

存储模块是本地证据的最后一道边界：所有路径都必须落在 root 下，清理只能
删除本模块创建的事件记录和其引用的截图，网络状态不会影响这条本地链路。
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict
import json
import logging
import os
import re
import shutil
import threading
import cv2


class StorageError(RuntimeError):
    """事件目录越界、编码失败或空间策略无法满足时的异常。"""
    pass


class EventStorage:
    """把事件和对应截图写入受限目录，并执行保留策略。"""

    def __init__(
            self,
            root,
            max_bytes=209715200,
            retention_days=7,
            min_free_bytes=104857600):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.retention_days = retention_days
        self.min_free_bytes = min_free_bytes
        self.cleaned_events = 0
        self.queue_delivery = False
        self._lock = threading.RLock()
        # History reads can be slow on the Pi.  Keep their index independent of
        # the save lock so an HTTP request cannot pause the detector loop.
        self._index_lock = threading.RLock()
        self._index_signature = None
        self._index_rows = None
        self._index_generation = 0

    def _safe(self, path):
        # 解析真实路径并拒绝符号链接，防止配置或事件字段把写入带出受限目录。
        path = Path(path)
        if not path.is_relative_to(self.root) or not path.resolve().is_relative_to(self.root):
            raise StorageError(f"Refusing path outside event storage: {path}")
        for component in (path, *path.parents):
            if component == self.root:
                break
            if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
                raise StorageError(f"Refusing linked event storage path: {component}")
        return path

    def recent_events(self, limit=50):
        """按需读取已落盘的近期事件，不在逐帧检测中扫描磁盘。"""
        if not isinstance(limit, int) or not 0 <= limit <= 200:
            raise StorageError("Event history limit must be between 0 and 200")
        if limit == 0:
            return []
        try:
            rows = list(reversed([row for _, row in self._indexed_rows()]))
            rows.sort(key=lambda row: row["occurred_at"], reverse=True)
            return rows[:limit]
        except (OSError, ValueError, KeyError, TypeError, StorageError) as exc:
            if isinstance(exc, StorageError):
                raise
            raise StorageError(f"Cannot read event history: {exc}") from exc

    def snapshot(self, event_id):
        """只按合法事件 ID 读取其日志声明的专用 JPEG。"""
        if not isinstance(event_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,100}", event_id):
            raise StorageError("Invalid event_id")
        try:
            for _, row in self._indexed_rows():
                if row["event_id"] == event_id:
                    if row["snapshot_path"] is None:
                        return None
                    path = self._safe(self.root / row["snapshot_path"])
                    return path.read_bytes() if path.is_file() else None
            return None
        except (OSError, ValueError, KeyError, TypeError, StorageError) as exc:
            if isinstance(exc, StorageError):
                raise
            raise StorageError(f"Cannot read snapshot: {exc}") from exc

    def _log_signature(self):
        """Return a cheap signature that invalidates the history index on edits."""
        signature = []
        for path in sorted(self.root.glob("????-??-??/events.jsonl")):
            self._safe(path)
            stat = path.stat()
            signature.append((path.relative_to(self.root).as_posix(),
                              stat.st_size, stat.st_mtime_ns, stat.st_ino))
        return tuple(signature)

    def _indexed_rows(self):
        """Read and validate logs once per log-file generation.

        The lock only protects the cache.  In particular, it never nests the
        save lock, so a slow disk read cannot block ``save``.
        """
        with self._index_lock:
            before = self._log_signature()
            if self._index_signature == before and self._index_rows is not None:
                return self._index_rows
            generation = self._index_generation

        # Do not hold _index_lock while reading JSONL.  save() only needs that
        # lock to invalidate the pointer, so a slow disk read cannot delay the
        # detector's event save or its return to the processing loop.
        rows = tuple(self._rows())
        after = self._log_signature()
        if after != before:
            # A writer changed a log while it was being read.  Re-read once so
            # callers never receive a known mixed-generation index.
            rows = tuple(self._rows())
            after = self._log_signature()

        with self._index_lock:
            if generation == self._index_generation:
                self._index_signature = after
                self._index_rows = rows
        return rows

    def _invalidate_index(self):
        with self._index_lock:
            self._index_generation += 1
            self._index_signature = None
            self._index_rows = None

    def _rows(self):
        # 读取现有 JSONL 时再次校验 event_id 与 snapshot_path 的一一对应关系，
        # 这样清理逻辑不会误删外部文件或接受被篡改的记录。
        rows = []
        for p in sorted(self.root.glob("????-??-??/events.jsonl")):
            self._safe(p)
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise StorageError("Event record must be a JSON object")
                    event_id = row.get("event_id", "")
                    occurred_at = row.get("occurred_at")
                    snapshot_path = row.get("snapshot_path")
                    if not isinstance(event_id, str) or not isinstance(
                            occurred_at, str) or (snapshot_path is not None and
                                                  not isinstance(snapshot_path, str)):
                        raise StorageError("Event record has invalid field types")
                    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", event_id):
                        raise StorageError("Event record has invalid event_id")
                    if snapshot_path is None:
                        rows.append((p, row))
                        continue
                    expected = (p.parent.relative_to(self.root) /
                                (event_id + ".jpg")).as_posix()
                    if not re.fullmatch(
                        r"[A-Za-z0-9_-]{1,100}",
                            event_id) or row.get("snapshot_path") != expected:
                        raise StorageError(
                            "Event record references a file that is not its own snapshot")
                    self._safe(self.root / expected)
                    rows.append((p, row))
        return rows

    def _rewrite(self, path, rows):
        # 先完整写入同目录临时文件并 fsync，再原子替换正式日志，避免留下半行 JSON。
        temp = self._safe(path.with_suffix(".tmp"))
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as out:
                out.write(
                    "".join(
                        json.dumps(
                            x,
                            ensure_ascii=False) +
                        "\n" for x in rows))
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, self._safe(path))
        finally:
            if temp.is_file():
                temp.unlink()

    def _plan_save(self, target, record, required):
        """Plan evictions without modifying any existing evidence."""
        rows = self._rows()
        total = self._usage()
        free = shutil.disk_usage(self.root).free
        needed = max(total + required - self.max_bytes,
                     self.min_free_bytes + required - free, 0)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        by_log = defaultdict(list)
        for log, row in rows:
            if row["event_id"] == record["event_id"]:
                raise StorageError("Event ID already exists")
            by_log[log].append(row)
        removals = defaultdict(set)
        snapshots = defaultdict(list)
        reclaimed = 0
        for log, row in sorted(rows, key=lambda item: item[1]["occurred_at"]):
            stamp = datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00"))
            if stamp >= cutoff and reclaimed >= needed:
                continue
            if row.get("delivery_state") == "pending":
                continue
            if not removals[log]:
                # Account for line endings and formatting of older JSONL files.
                reclaimed += log.stat().st_size - sum(self._line_size(r) for r in by_log[log])
            removals[log].add(row["event_id"])
            reclaimed += self._line_size(row)
            if row["snapshot_path"]:
                snap = self._safe(self.root / row["snapshot_path"])
                if snap.is_file():
                    reclaimed += snap.stat().st_size
                    snapshots[log].append(snap)
        if reclaimed < needed:
            raise StorageError("Event storage capacity or minimum free-space threshold exceeded")
        # Commit the new event first. A failed new write must leave every victim intact.
        retained = {log: [r for r in by_log[log] if r["event_id"] not in ids]
                    for log, ids in removals.items()}
        new_rows = retained.pop(target, by_log[target]) + [record]
        return new_rows, retained, snapshots, removals

    @staticmethod
    def _line_size(row):
        return len((json.dumps(row, ensure_ascii=False) + "\n").encode("utf8"))

    def _usage(self):
        # Upgrades may leave the former service trace here. It is unrelated to
        # the event quota but still contributes to actual disk free-space pressure.
        legacy = self.root / "service-frames.csv"
        return sum(self._safe(p).stat().st_size for p in self.root.rglob("*")
                   if p.is_file() and p != legacy)

    def pending_events(self):
        return [row for _, row in self._indexed_rows() if row.get("delivery_state") == "pending"]

    def acknowledge(self, event_ids):
        """Commit broker receipts before the sender releases these IDs."""
        with self._lock:
            groups = defaultdict(list)
            changed = set()
            for log, row in self._rows():
                if row["event_id"] in event_ids and row.get("delivery_state") == "pending":
                    row["delivery_state"] = "acked"
                    changed.add(log)
                groups[log].append(row)
            for log in changed:
                self._rewrite(log, groups[log])
            self._invalidate_index()

    def attach_snapshot(self, event, image):
        """Attach an optional JPEG only while the durable record still exists."""
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            raise StorageError("JPEG encoding failed")
        with self._lock:
            day = datetime.fromisoformat(event.occurred_at.replace("Z", "+00:00")).strftime("%Y-%m-%d")
            log = self._safe(self.root / day / "events.jsonl")
            rows = [row for path, row in self._rows() if path == log]
            row = next((r for r in rows if r["event_id"] == event.event_id), None)
            if row is None:
                return False
            snap = self._safe(log.parent / (event.event_id + ".jpg"))
            if snap.exists():
                raise StorageError("Snapshot already exists")
            previous = self._line_size(row)
            row["snapshot_path"] = snap.relative_to(self.root).as_posix()
            row["snapshot_note"] = None
            required = encoded.nbytes + self._line_size(row) - previous
            if (self._usage() + required > self.max_bytes or
                    shutil.disk_usage(self.root).free - required < self.min_free_bytes):
                return False
            temp = self._safe(snap.with_suffix(".jpg.tmp"))
            try:
                temp.write_bytes(encoded.tobytes())
                os.replace(temp, snap)
                try:
                    self._rewrite(log, rows)
                except Exception:
                    snap.unlink()
                    raise
            finally:
                temp.unlink(missing_ok=True)
            event.snapshot_path = row["snapshot_path"]
            event.snapshot_note = None
            self._invalidate_index()
            return True

    def save(self, event, image):
        """保存事件与截图，并避免 HTTP 历史读取观察到中间状态。"""
        with self._lock:
            result = self._save(event, image)
            self._invalidate_index()
            return result

    def _save(self, event, image):
        # 先完成编码、容量估算和清理，再写入截图与日志；任一步失败都回滚路径字段。
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", event.event_id):
            raise StorageError("Invalid event_id")
        created = False
        snap = None
        event.snapshot_path = None
        try:
            day = datetime.fromisoformat(
                event.occurred_at.replace(
                    "Z", "+00:00")).strftime("%Y-%m-%d")
            folder = self._safe(self.root / day)
            folder.mkdir(exist_ok=True)
            snap = self._safe(folder / (event.event_id + ".jpg"))
            if snap.exists():
                raise StorageError("Event ID already exists")
            # 截图和 JSONL 使用同一个事件 ID，后续读取记录时可以验证二者没有串联。
            encoded = None
            if image is not None:
                ok, encoded = cv2.imencode(
                    ".jpg", image, [
                        cv2.IMWRITE_JPEG_QUALITY, 75])
                if not ok:
                    raise StorageError("JPEG encoding failed")
                event.snapshot_path = snap.relative_to(self.root).as_posix()
            record = event.to_dict()
            if self.queue_delivery:
                record["delivery_state"] = "pending"
            required = (encoded.nbytes if encoded is not None else 0) + self._line_size(record)
            if required > self.max_bytes:
                raise StorageError("Single event exceeds event storage budget")
            log = self._safe(folder / "events.jsonl")
            rows, retained, snapshots, removals = self._plan_save(log, record, required)
            # JPEG 先写临时文件再替换；日志随后原子重写，避免记录指向不存在的半文件。
            if encoded is not None:
                temp = self._safe(snap.with_suffix(".jpg.tmp"))
                try:
                    temp.write_bytes(encoded.tobytes())
                    os.replace(temp, snap)
                    created = True
                finally:
                    temp.unlink(missing_ok=True)
            self._rewrite(log, rows)
        except (OSError, ValueError, StorageError) as exc:
            # 清理已经创建的截图，并把事件恢复为“尚未保存”的状态交给流水线统计失败。
            if created and snap and snap.is_file():
                snap.unlink()
            event.snapshot_path = None
            raise StorageError(f"{self.root}: {exc}") from exc
        # Only unlink JPEGs once their own log no longer references them.
        for path in removals:
            try:
                if path != log:
                    self._rewrite(path, retained[path])
                self.cleaned_events += len(removals[path])
                for old_snapshot in snapshots[path]:
                    old_snapshot.unlink()
            except OSError:
                logging.exception("Event saved; could not finish retention for %s", path)
        return event
