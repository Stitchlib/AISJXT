"""配置管理：单一配置源（Single Source of Truth）。

- 优先加载 edge/config/config.json（持久化格式，零依赖）。
- 若存在 edge/config/config.yaml 且 PyYAML 可用，也可读取。
- 所有模块通过 ConfigManager().get() 读取配置，避免散落的硬编码常量。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from .models import CameraType, DefectTypeConfig

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class CameraConfig(BaseModel):
    id: str
    name: str
    type: str = "simulated"
    source: str = "0"
    enabled: bool = True
    # 凭据（仅对 rtsp/http 类摄像头有效）；留空表示匿名。
    # 注意：取流 URL 已内嵌 user:pass@，这里单独保存便于展示/更新/重连。
    username: Optional[str] = None
    password: Optional[str] = None


class AppConfig(BaseModel):
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    confidence_threshold: float = 0.5
    iou_threshold: float = 0.45
    model_path: Optional[str] = None
    enable_simulation: bool = True  # 当无可用模型时降级到标注仿真
    db_path: str = "data/inspection.db"
    push_interval_frames: int = 10
    cameras: List[CameraConfig] = Field(default_factory=list)
    active_camera_id: Optional[str] = None  # 当前检测使用的摄像头；为空则取列表首个
    auto_discover: bool = False  # 启动时是否自动扫描并注册同一局域网内的网络摄像头
    # 自动发现时使用的默认凭据（留空表示匿名）；避免每次手动输入。
    discover_username: Optional[str] = None
    discover_password: Optional[str] = None
    # 视频流：采集帧率，以及最后一个观看端离开后继续保持摄像头打开的秒数
    # （linger 避免前端刷新页面时反复开关摄像头，RTSP 重连往往要数秒）
    stream_fps: int = 15
    stream_linger_seconds: float = 6.0
    # 认证：JWT 签名密钥（生产环境务必通过环境变量覆盖）
    secret_key: str = "aiqc-local-dev-secret-change-me-2026-prod"
    token_expire_minutes: int = 60 * 12
    # 邮件/告警
    smtp_enabled: bool = False
    smtp_host: str = "smtp.example.com"
    smtp_port: int = 465
    smtp_mode: str = "ssl"  # ssl | starttls | plain
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = "aiqc@noreply.local"
    # 自定义瑕疵类型（基准 4 类，可增删）
    defect_types: List[DefectTypeConfig] = Field(
        default_factory=lambda: [
            DefectTypeConfig(name="线头", color="#f56c6c"),
            DefectTypeConfig(name="跳线", color="#e6a23c"),
            DefectTypeConfig(name="色差", color="#409eff"),
            DefectTypeConfig(name="破洞", color="#9254de"),
        ]
    )

    @property
    def defect_class_names(self) -> List[str]:
        return [d.name for d in self.defect_types if d.enabled]


class ConfigManager:
    """线程安全的单例配置管理器。"""

    _instance: Optional["ConfigManager"] = None
    _lock = threading.Lock()

    def __new__(cls, path: Optional[str | Path] = None) -> "ConfigManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        # 允许通过环境变量覆盖配置路径（便于容器化部署）
        cfg_path = path or cls._resolve_path()
        if not cls._instance._initialized or str(cls._instance.path) != str(cfg_path):
            cls._instance._init(cfg_path)
        return cls._instance

    @staticmethod
    def _resolve_path() -> Path:
        # 布局无关解析：同时兼容本地（.../edge/src）与容器（/app/src）结构
        base = Path(__file__).resolve().parent.parent
        candidates = [
            base / "config" / "config.json",
            Path.cwd() / "edge" / "config" / "config.json",
            Path.cwd() / "config" / "config.json",
        ]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    def _init(self, path: str | Path) -> None:
        self.path = Path(path)
        self.config = self._load()
        self._initialized = True

    def _load(self) -> AppConfig:
        if self.path.exists():
            try:
                text = self.path.read_text(encoding="utf-8")
                if self.path.suffix in (".yaml", ".yml"):
                    import yaml  # type: ignore
                    data = yaml.safe_load(text) or {}
                else:
                    data = json.loads(text)
                # 将配置文件中相对路径解析为绝对路径，避免后端因启动工作目录不同
                # 而创建多个数据文件或出现"readonly database"错误。
                # 约定：edge/config/config.json 的父目录之上一级即项目根（edge/ 或容器内 /app/）；
                # 若 edge/ 同级存在 frontend/ 目录，说明是本地仓库，项目根为 edge/ 的父目录。
                base = self.path.parent.parent
                if (base.parent / "frontend").exists():
                    base = base.parent
                for key in ("db_path", "model_path"):
                    val = data.get(key)
                    if val and not Path(val).is_absolute():
                        data[key] = str((base / val).resolve())
                return AppConfig(**data)
            except Exception:
                # 配置损坏时不崩溃，回退到默认配置
                return AppConfig()
        return AppConfig()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.config.model_dump()
        if self.path.suffix in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
                self.path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
                return
            except Exception:
                pass
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def get(self) -> AppConfig:
        return self.config

    def update(self, **kwargs) -> AppConfig:
        allowed = {k: v for k, v in kwargs.items() if v is not None and hasattr(self.config, k)}
        for k, v in allowed.items():
            setattr(self.config, k, v)
        self.save()
        return self.config

    # ---------- 摄像头配置增删（持久化） ----------
    def add_camera(self, cam: CameraConfig) -> None:
        if any(c.id == cam.id for c in self.config.cameras):
            raise ValueError(f"摄像头 id 已存在: {cam.id}")
        self.config.cameras.append(cam)
        self.save()

    def remove_camera(self, cam_id: str) -> None:
        self.config.cameras = [c for c in self.config.cameras if c.id != cam_id]
        if self.config.active_camera_id == cam_id:
            self.config.active_camera_id = None
        self.save()

    # ---------- 当前（激活）摄像头 ----------
    def get_active_camera_id(self) -> Optional[str]:
        """返回当前激活摄像头 id（不存在于列表时返回 None）。"""
        aid = self.config.active_camera_id
        if aid and any(c.id == aid for c in self.config.cameras):
            return aid
        return None

    def set_active_camera(self, cam_id: str) -> None:
        if not any(c.id == cam_id for c in self.config.cameras):
            raise ValueError(f"摄像头不存在: {cam_id}")
        self.config.active_camera_id = cam_id
        self.save()

    def update_camera_source(self, cam_id: str, source: str) -> None:
        for c in self.config.cameras:
            if c.id == cam_id:
                c.source = source
                self.save()
                return
        raise ValueError(f"摄像头不存在: {cam_id}")
