import subprocess,sys,os
import pytest
from pathlib import Path

def call(*args):
    env=os.environ.copy()
    env["PYTHONPATH"]=str(Path(__file__).parents[1]/"src")
    env["PYTHONUTF8"]="1"
    return subprocess.run([sys.executable,"-m","edgevision.cli",*args],env=env,capture_output=True,text=True,encoding="utf-8")

def test_cli_help_exposes_replay_run_and_check():
    p=call("--help")
    assert p.returncode==0
    assert "replay" in p.stdout and "run" in p.stdout and "check" in p.stdout

def test_infer_missing_image_exits_with_clear_error():
    p=call("infer","--image","missing-image.png")
    assert p.returncode != 0
    assert "image" in p.stderr.lower()

def test_no_output_file_can_escape_project_directory(tmp_path):
    from edgevision.cli import output_path
    import pytest
    with pytest.raises(ValueError,match="project"):
        output_path("../outside.json",tmp_path)

def test_image_loader_handles_unicode_path(tmp_path):
    from edgevision.cli import read_image
    import cv2, numpy as np
    p=tmp_path/"测试图像.png"
    ok,buffer=cv2.imencode(".png",np.zeros((8,8,3),np.uint8))
    assert ok
    p.write_bytes(buffer.tobytes())
    assert read_image(p).shape==(8,8,3)

def test_config_argument_cannot_relocate_project_root(tmp_path):
    from edgevision.cli import DEFAULT_ROOT
    p=call("assets","--config",str(DEFAULT_ROOT.parent/"external-never-created.yaml"))
    assert p.returncode!=0
    assert "configuration must stay inside project" in p.stderr.lower()

def test_capture_check_saves_rotated_pixels(tmp_path,monkeypatch,capsys):
    import json,time,yaml
    import numpy as np
    from edgevision import cli
    from edgevision.types import Frame
    data=yaml.safe_load((cli.DEFAULT_ROOT/"config.example.yaml").read_text())
    data["input"]["rotation"]=180
    config_path=tmp_path/"config.yaml"
    config_path.write_text(yaml.safe_dump(data))
    class Camera:
        reconnects=0
        def __init__(self,*args):pass
        def __iter__(self):
            image=np.zeros((40,60,3),np.uint8)
            image[-10:,-10:]=255
            yield Frame(0,time.monotonic(),image,"camera",None)
        def close(self):pass
    monkeypatch.setattr(cli,"DEFAULT_ROOT",tmp_path)
    monkeypatch.setattr(cli,"UvcCameraSource",Camera)
    assert cli.main(["check","--config",str(config_path),"--input","uvc",
                     "--frames","1","--snapshot","snapshot.jpg"])==0
    image=cli.read_image(tmp_path/"snapshot.jpg")
    assert image[0,0].min()>240 and image[-1,-1].max()<15
    assert json.loads(capsys.readouterr().out)["input_rotation"]==180

def test_capture_check_skips_snapshot_when_frame_is_below_focus_threshold(tmp_path, monkeypatch, capsys):
    import json, time, yaml, numpy as np
    from edgevision import cli
    from edgevision.types import Frame
    data = yaml.safe_load((cli.DEFAULT_ROOT / "config.example.yaml").read_text())
    data["input"]["min_sharpness"] = 1e12
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(data))
    class Camera:
        reconnects = 0
        def __init__(self, *args): pass
        def __iter__(self):
            yield Frame(0, time.monotonic(), np.zeros((40, 60, 3), np.uint8), "camera", None)
        def close(self): pass
    monkeypatch.setattr(cli, "DEFAULT_ROOT", tmp_path)
    monkeypatch.setattr(cli, "UvcCameraSource", Camera)
    assert cli.main(["check", "--config", str(config_path), "--input", "uvc",
                     "--frames", "1", "--snapshot", "blur.jpg"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["snapshot_skipped"] is True
    assert not (tmp_path / "blur.jpg").exists()

@pytest.mark.parametrize("command",["run","infer"])
def test_runtime_rejects_unregistered_weights_before_loading_detector(tmp_path,monkeypatch,command):
    import yaml,cv2,numpy as np
    from edgevision import cli
    data=yaml.safe_load((cli.DEFAULT_ROOT/"config.example.yaml").read_text())
    data["model"]["path"]="models/unregistered.onnx"
    config_path=tmp_path/"config.yaml";config_path.write_text(yaml.safe_dump(data))
    (tmp_path/"models").mkdir();(tmp_path/"models/unregistered.onnx").write_bytes(b"unregistered")
    ok,buffer=cv2.imencode(".png",np.zeros((8,8,3),np.uint8));assert ok
    (tmp_path/"input.png").write_bytes(buffer.tobytes())
    def unexpected_detector(*args):raise AssertionError("Unverified weights reached inference")
    monkeypatch.setattr(cli,"DEFAULT_ROOT",tmp_path)
    monkeypatch.setattr(cli,"Detector",unexpected_detector)
    args=[command,"--config",str(config_path)]
    if command=="infer":args.extend(["--image","input.png","--model","models/unregistered.onnx"])
    assert cli.main(args)==2
