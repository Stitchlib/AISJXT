"""配置管理：单一配置源（Single Source of Truth）。

- 优先加载 edge/config/config.json（持久化格式，零依赖）。
- 若存在 edge/config/config.yaml 且 PyYAML 可用，也可读取。
- 所有模块通过 ConfigManager().get() 读取配置，避免散落的硬编码常量。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from .models import DefectTypeConfig, RoiRect

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

# 默认密钥（仅本地开发用）。生产必须通过环境变量 AIQC_SECRET_KEY 覆盖。
DEFAULT_SECRET_KEY = "aiqc-local-dev-secret-change-me-2026-prod"
DEFAULT_ADMIN_PASSWORD = "admin123"


def _int(env_val: Optional[str], setter) -> None:
    """若环境变量存在且可解析为整数，则调用 setter 写入配置。"""
    if env_val:
        try:
            setter(int(env_val))
        except (TypeError, ValueError):
            pass


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
    # 连接状态（持久化）：online / offline / unknown。运行时可由帧总线实际取流情况回写，
    # 也允许通过 PUT /cameras/{id} 显式置为 online 以反映"真实摄像头已接入"。
    status: str = "unknown"
    # 检测区域（第二期 G6）：归一化矩形列表，空表示全画面检测
    roi: List[RoiRect] = Field(default_factory=list)


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
    # 安全/治理相关运行时配置（均可经环境变量覆盖，见 _apply_env_overrides）
    data_retention_days: int = 180          # 检测数据保留天数，到期自动清理
    inspection_interval_ms: int = 1000      # 检测循环节拍（毫秒），可随产线节拍调节
    # 缺陷图片留存（第二期 G1）：none=不落盘 / defect_only=仅有缺陷帧 / all=全部 / sample=抽样
    save_image_mode: str = "defect_only"
    image_quota_gb: float = 10.0            # 图片目录容量上限（GB），超限按最旧优先清理
    image_retention_days: int = 90          # 图片保留天数，到期自动清理
    image_dir: Optional[str] = None         # 图片根目录；None=数据库同级的 images/ 目录
    max_upload_mb: int = 200                # 模型上传大小上限（MB）
    allowed_origins: List[str] = Field(default_factory=list)  # CORS 白名单，空=仅同源
    audit_enabled: bool = True              # 管理操作审计日志开关
    timezone: str = "Asia/Shanghai"         # 报表展示时区
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
    # 备份与恢复（第二期 G7a）：备份目录（None=数据库同级的 backups/）与保留份数
    backup_dir: Optional[str] = None
    backup_retention: int = 7
    # 训练样本导出（第二期 1.3）：单次导出样本数上限（配额保护，防超大 zip 撑爆内存/带宽）
    sample_export_limit: int = 2000

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
        self._degraded = False
        self._degraded_reason = ""
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
                cfg = AppConfig(**data)
                self._apply_env_overrides(cfg)
                return cfg
            except Exception as e:  # 配置损坏：备份原文件、标记降级，绝不直接崩溃
                self._degraded_reason = f"配置文件解析失败（已备份）：{e}"
                try:
                    if self.path.exists():
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        corrupt = self.path.with_name(f"config.json.corrupt-{ts}")
                        shutil.copy(self.path, corrupt)
                        self._degraded_reason += f"；原文件已备份为 {corrupt.name}"
                except Exception as be:  # pragma: no cover - 备份失败不阻断启动
                    self._degraded_reason += f"；备份失败：{be}"
                self._degraded = True
                logger = logging.getLogger("config_manager")
                logger.error("配置降级启动：%s", self._degraded_reason)
                cfg = AppConfig()
                self._apply_env_overrides(cfg)
                return cfg
        cfg = AppConfig()
        self._apply_env_overrides(cfg)
        return cfg

    @staticmethod
    def _apply_env_overrides(cfg: "AppConfig") -> None:
        """环境变量覆盖机制（H5）：生产环境务必通过环境变量覆盖敏感/环境相关配置。

        支持：AIQC_SECRET_KEY / AIQC_ADMIN_PASSWORD(由 AuthService 处理) /
        AIQC_ALLOWED_ORIGINS(逗号分隔) / AIQC_DATA_RETENTION_DAYS /
        AIQC_INSPECTION_INTERVAL_MS / AIQC_MAX_UPLOAD_MB / AIQC_TOKEN_EXPIRE_MINUTES
        """
        env_secret = os.environ.get("AIQC_SECRET_KEY")
        if env_secret:
            cfg.secret_key = env_secret
        env_origins = os.environ.get("AIQC_ALLOWED_ORIGINS")
        if env_origins:
            cfg.allowed_origins = [o.strip() for o in env_origins.split(",") if o.strip()]
        _int(env_val=os.environ.get("AIQC_DATA_RETENTION_DAYS"), setter=lambda v: setattr(cfg, "data_retention_days", v))
        _int(env_val=os.environ.get("AIQC_INSPECTION_INTERVAL_MS"), setter=lambda v: setattr(cfg, "inspection_interval_ms", v))
        # 缺陷图片留存（第二期 G1）
        env_mode = os.environ.get("AIQC_SAVE_IMAGE_MODE")
        if env_mode and env_mode.strip().lower() in ("none", "defect_only", "all", "sample"):
            cfg.save_image_mode = env_mode.strip().lower()
        _float_or_int = os.environ.get("AIQC_IMAGE_QUOTA_GB")
        if _float_or_int:
            try:
                cfg.image_quota_gb = float(_float_or_int)
            except (TypeError, ValueError):
                pass
        _int(env_val=os.environ.get("AIQC_IMAGE_RETENTION_DAYS"), setter=lambda v: setattr(cfg, "image_retention_days", v))
        env_img_dir = os.environ.get("AIQC_IMAGE_DIR")
        if env_img_dir:
            cfg.image_dir = env_img_dir
        _int(env_val=os.environ.get("AIQC_MAX_UPLOAD_MB"), setter=lambda v: setattr(cfg, "max_upload_mb", v))
        _int(env_val=os.environ.get("AIQC_TOKEN_EXPIRE_MINUTES"), setter=lambda v: setattr(cfg, "token_expire_minutes", v))
        # 备份与恢复（第二期 G7a）
        env_bdir = os.environ.get("AIQC_BACKUP_DIR")
        if env_bdir:
            cfg.backup_dir = env_bdir
        _int(env_val=os.environ.get("AIQC_BACKUP_RETENTION"), setter=lambda v: setattr(cfg, "backup_retention", v))
        # 训练样本导出上限（第二期 1.3）
        _int(env_val=os.environ.get("AIQC_SAMPLE_EXPORT_LIMIT"), setter=lambda v: setattr(cfg, "sample_export_limit", v))
        # 容器化部署路径覆盖（H6 部署修复）：允许通过环境变量直接指定数据 / 模型路径，
        # 避免配置文件中写死的宿主机绝对路径（如 Windows 盘符路径）在容器内被误判为相对路径。
        #   AIQC_DB_PATH     -> 持久化卷，如 /app/data/inspection.db
        #   AIQC_MODEL_PATH  -> 内置权重，如 /app/model/yolov8n.pt
        env_db = os.environ.get("AIQC_DB_PATH")
        if env_db:
            cfg.db_path = env_db
        env_model = os.environ.get("AIQC_MODEL_PATH")
        if env_model:
            cfg.model_path = env_model

    def is_degraded(self) -> bool:
        return self._degraded

    def degraded_reason(self) -> str:
        return self._degraded_reason

    def security_warnings(self) -> List[str]:
        """启动时安全自检（H5）：返回需要告警的隐患清单。"""
        warnings: List[str] = []
        if self.config.secret_key == DEFAULT_SECRET_KEY and not os.environ.get("AIQC_SECRET_KEY"):
            warnings.append(
                "secret_key 仍使用默认硬编码值，存在被伪造 admin 令牌的风险！"
                "请通过环境变量 AIQC_SECRET_KEY 覆盖（生产部署必做）。"
            )
        if not os.environ.get("AIQC_ADMIN_PASSWORD"):
            warnings.append(
                "管理员初始口令仍为默认值 admin/admin123，请通过环境变量 "
                "AIQC_ADMIN_PASSWORD 覆盖或在首次登录后立即修改。"
            )
        if self.config.allowed_origins == ["*"] or not self.config.allowed_origins:
            # 空列表=仅同源，属安全默认；仅当显式 * 才告警
            if self.config.allowed_origins == ["*"]:
                warnings.append("CORS 允许任意来源（*），存在跨站读取 API 的风险，请通过 AIQC_ALLOWED_ORIGINS 收敛。")
        return warnings

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 兼容 pydantic v1（.dict()）与 v2（.model_dump()）：运行环境版本差异不应让配置保存失败
        payload = self.config.model_dump() if hasattr(self.config, "model_dump") else self.config.dict()
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
