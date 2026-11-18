import math
import pytest
import yaml

def write_config(tmp_path, **overrides):
    from pathlib import Path
    data = yaml.safe_load((Path(__file__).parents[1] / "config.example.yaml").read_text())
    for key, val in overrides.items():
        section, name = key.split("__")
        data[section][name] = val
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data))
    return p

def test_relative_paths_resolve_against_config_not_cwd(tmp_path):
    from edgevision.config import load_config
    cfg = load_config(write_config(tmp_path))
    assert cfg.model.path == tmp_path / "models/yolox_nano.onnx"
    assert cfg.output.directory == tmp_path / "output"
    assert cfg.mqtt.host == "127.0.0.1"

@pytest.mark.parametrize("overrides", [
    {"input__type": "unknown"}, {"roi__points": []},
    {"roi__points": [[0,0],[1,1],[0.5,0.5]]},
    {"roi__points": [[0,0],[2,0],[0,1]]},
    {"events__cooldown_seconds": -1}, {"model__confidence": math.nan},
    {"model__threads": 0}, {"model__path": ""}, {"output__max_bytes": 0},
    {"input__rotation": 13},
    {"input__rotation": True}, {"input__rotation": 180.0},
    {"input__mirror_horizontal": "false"},
    {"roi__enabled": "false"},
    {"input__min_sharpness": -1}, {"input__focus_warmup_frames": 1.5},
])
def test_invalid_configuration_rejected(tmp_path, overrides):
    from edgevision.config import ConfigError, load_config
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, **overrides))

def test_missing_model_section_is_actionable(tmp_path):
    from edgevision.config import ConfigError, load_config
    p = tmp_path / "config.yaml"; p.write_text("roi: {}")
    with pytest.raises(ConfigError, match="model"):
        load_config(p)

@pytest.mark.parametrize("rotation",[0,90,180,270])
def test_supported_input_rotations_load(tmp_path,rotation):
    from edgevision.config import load_config
    assert load_config(write_config(tmp_path,input__rotation=rotation)).input.rotation==rotation

@pytest.mark.parametrize("mirror",[False,True])
def test_mirror_option_is_a_boolean(tmp_path,mirror):
    from edgevision.config import load_config
    assert load_config(write_config(tmp_path,input__mirror_horizontal=mirror)).input.mirror_horizontal is mirror

@pytest.mark.parametrize("enabled", [True, False])
def test_roi_enabled_option_is_loaded(tmp_path, enabled):
    from edgevision.config import load_config
    assert load_config(write_config(tmp_path, roi__enabled=enabled)).roi.enabled is enabled
