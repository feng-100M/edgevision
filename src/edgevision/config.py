"""读取并校验 YAML 配置；所有本地路径都相对于配置文件解析。

配置是运行链路的入口：它同时决定输入来源、模型参数、归一化 ROI、
事件策略、输出配额和 MQTT 地址。把边界检查集中在这里，可以让后续
模块假设收到的是已经合法的值。
"""
from dataclasses import dataclass, fields
from pathlib import Path
import math
import yaml


class ConfigError(ValueError):
    """配置缺失、类型错误或超出项目约束时抛出的统一异常。"""
    pass


@dataclass
class InputConfig:
    type: str = "video"
    path: Path = Path("data/videos/vtest.avi")
    device: str = "/dev/video0"
    width: int = 640
    height: int = 480
    fps: float = 15.
    retry_seconds: float = 1.
    focus_warmup_frames: int = 30
    min_sharpness: float = 40.
    rotation: int = 0
    mirror_horizontal: bool = False


@dataclass
class ModelConfig:
    path: Path
    threads: int = 2
    confidence: float = .35
    nms: float = .45


@dataclass
class RoiConfig:
    name: str
    points: list
    enabled: bool = True


@dataclass
class EventConfig:
    cooldown_seconds: float = 2.
    emit_leave: bool = True


@dataclass
class OutputConfig:
    directory: Path = Path("output")
    max_bytes: int = 209715200
    retention_days: int = 7
    min_free_bytes: int = 104857600


@dataclass
class MqttConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 1883
    topic: str = "edgevision/alerts"


@dataclass
class AppConfig:
    input: InputConfig
    model: ModelConfig
    roi: RoiConfig
    events: EventConfig
    output: OutputConfig
    mqtt: MqttConfig

# 加载配置,验证配置文件是否符合要求
def load_config(path):
    """加载配置并返回 ``AppConfig``，同时把相对路径转换为绝对路径。

    这里还会检查输入类型、旋转角度、阈值、ROI 面积、MQTT topic 和
    输出边界。调用方只需要处理 ``ConfigError``，不必重复解析 YAML。
    """
    # 先固定配置文件自身的位置；后续所有相对路径都以它的目录为基准，
    path = Path(path).resolve()

    try:
        # YAML 只在入口解析一次，之后用 dataclass 传递结构化配置。
        data = yaml.safe_load(path.read_text(encoding="utf-8"))

        if not isinstance(data, dict):
            raise ConfigError("Configuration must be a YAML mapping")

        # model 和 roi 是没有合理默认值的核心段落，缺失时应在启动阶段失败。
        for required in ("model", "roi"):
            if required not in data:
                raise ConfigError(f"Missing {required} section")

        if not data["model"].get("path"):
            raise ConfigError("model.path must not be empty")

        # 每个 YAML 段映射到一个配置对象，后续校验和业务代码无需处理原始字典。
        types = {
            "input": InputConfig,
            "model": ModelConfig,
            "roi": RoiConfig,
            "events": EventConfig,
            "output": OutputConfig,
            "mqtt": MqttConfig}
        config = AppConfig(**{k: t(**data.get(k, {}))
                           for k, t in types.items()})

        # 输入、模型、输出和事件参数在这里集中校验，避免流水线运行到一半才发现配置错误。
        if config.input.type not in ("video", "uvc"):
            raise ConfigError("input.type must be video or uvc")
        if not isinstance(
                config.input.rotation,
                int) or config.input.rotation not in (
                0,
                90,
                180,
                270):
            raise ConfigError(
                "input.rotation must be an integer: 0, 90, 180 or 270 clockwise")
        if not isinstance(config.input.mirror_horizontal, bool):
            raise ConfigError("input.mirror_horizontal must be a boolean")
        if not isinstance(config.roi.enabled, bool):
            raise ConfigError("roi.enabled must be a boolean")
        for label, value in (("width", config.input.width), ("height", config.input.height),
                             ("fps", config.input.fps), ("retry_seconds", config.input.retry_seconds),
                             ("focus_warmup_frames", config.input.focus_warmup_frames),
                             ("threads", config.model.threads), ("max_bytes", config.output.max_bytes),
                             ("retention_days", config.output.retention_days)):
            if isinstance(value, bool) or not math.isfinite(
                    value) or value <= 0:
                raise ConfigError(f"{label} must be finite and positive")
        if not isinstance(config.model.threads, int):
            raise ConfigError("model.threads must be an integer")
        if not isinstance(config.input.focus_warmup_frames, int):
            raise ConfigError("input.focus_warmup_frames must be an integer")
        if not math.isfinite(config.input.min_sharpness) or config.input.min_sharpness < 0:
            raise ConfigError("input.min_sharpness must be finite and nonnegative")
        for label, value in (
                ("confidence", config.model.confidence), ("nms", config.model.nms)):
            if not math.isfinite(value) or not 0 < value <= 1:
                raise ConfigError(f"{label} must be in (0,1]")
        if not math.isfinite(
                config.events.cooldown_seconds) or config.events.cooldown_seconds < 0:
            raise ConfigError(
                "events.cooldown_seconds must be finite and nonnegative")
        if config.output.min_free_bytes < 0:
            raise ConfigError("min_free_bytes must be nonnegative")

        # ROI 存储的是 0..1 归一化点；除了范围，还要拒绝共线点组成的零面积多边形。
        p = config.roi.points
        if len(p) < 3 or any(
            len(v) != 2 or any(
                not math.isfinite(x) or not 0 <= x <= 1 for x in v) for v in p):
            raise ConfigError(
                "ROI requires at least three normalized points in [0,1]")
        area = sum(p[i][0] * p[(i + 1) %
                               len(p)][1] - p[(i + 1) %
                   len(p)][0] * p[i][1] for i in range(len(p)))
        if abs(area) < 1e-9:
            raise ConfigError("ROI polygon must have nonzero area")
        if not isinstance(
                config.mqtt.port,
                int) or not 1 <= config.mqtt.port <= 65535:
            raise ConfigError("mqtt.port must be in [1,65535]")
        if not config.mqtt.topic or any(c in config.mqtt.topic for c in "#+"):
            raise ConfigError("mqtt.topic must be a concrete publish topic")

        # 路径统一解析为绝对路径，后续模块可以安全地创建输出目录或打开模型。
        for obj, key in ((config.model, "path"), (config.input,
                         "path"), (config.output, "directory")):
            value = Path(getattr(obj, key))
            setattr(obj, key, (path.parent / value).resolve())

        return config

    except ConfigError:
        # 已经是面向用户的配置错误，保留原始信息和类型。
        raise

    except (OSError, TypeError, ValueError, KeyError, AttributeError, yaml.YAMLError) as exc:
        # 文件读取、YAML 解析和 dataclass 构造错误统一转换为启动期 ConfigError。
        raise ConfigError(f"{path}: {exc}") from exc
