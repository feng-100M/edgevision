"""下载固定版本的公开素材，并在替换前校验每个文件。

模型和回放素材属于输入契约的一部分；SHA-256 校验能把“代码变了”和
“输入文件变了”区分开，也避免把不明来源的二进制静默放进运行目录。
"""
from pathlib import Path
import hashlib
import json
import os
import tempfile
import urllib.request

ASSETS = {
    "models/yolox_nano.onnx": (
        "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx",
        "c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d"),
    "data/videos/vtest.avi": (
        "https://raw.githubusercontent.com/opencv/opencv/4.11.0/samples/data/vtest.avi",
        "45cddc9490be69345cbdab64ca583be65987e864ca408038e648db99e10516cf"),
    "data/images/basketball1.png": (
        "https://raw.githubusercontent.com/opencv/opencv/4.11.0/samples/data/basketball1.png",
        "ba06f6701f7260998b430c39b6557f775497e6ce7b1a74f0b7ea6af371bf54a6"),
}
def verify(path,expected):
    """计算文件 SHA-256，并在不匹配时拒绝继续。"""
    with Path(path).open("rb") as source:
        digest=hashlib.file_digest(source,"sha256").hexdigest()
    if digest!=expected:raise ValueError(f"SHA-256 mismatch: {path}")
    return digest

def verify_model(path,root):
    """校验原始模型或 manifest 中登记的派生模型。"""
    root=Path(root).resolve();path=Path(path).resolve()
    if not path.is_relative_to(root):raise ValueError("Model must remain inside project")
    relative=path.relative_to(root).as_posix()
    original=ASSETS["models/yolox_nano.onnx"][1]
    if relative=="models/yolox_nano.onnx":return verify(path,original)
    manifest=root/"models/manifest.json"
    data=json.loads(manifest.read_text()) if manifest.is_file() else {}
    entry=data.get("variants",{}).get(relative)
    if not entry or entry.get("base_sha256")!=original:
        raise ValueError("Model has no registered derivation from the pinned original")
    return verify(path,entry["sha256"])

def download_assets(root):
    """下载缺失素材到项目内临时文件，校验后原子替换到目标路径。"""
    root=Path(root).resolve()
    for name,(url,digest) in ASSETS.items():
        target=(root/name).resolve()
        if not target.is_relative_to(root):raise ValueError("Asset outside project")
        if target.is_file():
            verify(target,digest);continue
        target.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent,prefix=target.name+".",suffix=".part",delete=False) as out:
            temp=Path(out.name)
            try:
                with urllib.request.urlopen(url,timeout=60) as response:
                    while chunk:=response.read(1024*1024):out.write(chunk)
            except Exception:
                out.close();temp.unlink();raise
        try:
            verify(temp,digest);os.replace(temp,target)
        finally:
            if temp.is_file():temp.unlink()
    return {name:verify(root/name,digest) for name,(_,digest) in ASSETS.items()}
