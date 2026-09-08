"""模块间数据契约（Schema）。

所有跨模块数据交换都通过这些 Pydantic 模型完成，确保类型安全与一致性。
前端、WebSocket 推送、数据库持久化、API 响应共用同一套结构。
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, computed_field


def utc_iso() -> str:
    """统一以 UTC 时区存储时间戳（M13），格式 ISO 8601 含 +00:00，便于跨时区排序与聚合。"""
    return datetime.now(timezone.utc).isoformat()


class DefectClass(str, Enum):
    """服装瑕疵类别（源自原始需求：线头/跳线/色差/破洞）。"""
    THREAD_END = "线头"
    SKIPPED_STITCH = "跳线"
    COLOR_DIFF = "色差"
    HOLE = "破洞"
    UNKNOWN = "未知"


class BBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class Defect(BaseModel):
    class_name: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    bbox: BBox


class DetectionResult(BaseModel):
    """一次检测的结果。WebSocket 推送与数据库存储均使用此结构。"""
    id: Optional[int] = None
    timestamp: str = Field(default_factory=utc_iso)
    camera_id: str = "cam_sim"
    image_path: Optional[str] = None
    defects: List[Defect] = Field(default_factory=list)
    total_count: int = 0
    defect_count: int = 0
    defect_rate: float = 0.0
    processing_time_ms: float = 0.0
    is_simulation: bool = False
    # 指标语义版本（H3 治理）：1=含随机数的旧口径（不可信），2=真实检出口径。
    # 仿真数据标记 1、真实推理标记 2，报表据此区分历史不可信数据。
    metric_version: int = 2
    # 批次绑定（第二期 G4）：绑定后该条记录归属对应生产批次；未绑定为 None
    batch_id: Optional[str] = None

    def to_db_row(self) -> dict:
        """转换为数据库行（defects 序列化为 JSON 字符串）。"""
        return {
            "timestamp": self.timestamp,
            "camera_id": self.camera_id,
            "image_path": self.image_path,
            "defects": [d.model_dump() for d in self.defects],
            "total_count": self.total_count,
            "defect_count": self.defect_count,
            "defect_rate": self.defect_rate,
            "processing_time_ms": self.processing_time_ms,
            "is_simulation": self.is_simulation,
            "metric_version": self.metric_version,
            "batch_id": self.batch_id,
        }


class CameraType(str, Enum):
    """摄像头类型。

    历史问题：前端下拉给的是 rtsp/usb/http/simulation，而后端只认 usb/ip/network，
    导致用户选「RTSP」添加网络摄像头时，后端判定其"不是真实类型"从而根本不去取流，
    画面永远是仿真占位。这里补齐 RTSP/HTTP，并用 normalize_camera_type 统一别名。
    """

    USB = "usb"
    RTSP = "rtsp"
    HTTP = "http"
    IP = "ip"
    NETWORK = "network"
    SIMULATED = "simulated"


# 类型别名归一化表（大小写不敏感）。左边是各处可能出现的写法，右边是标准值。
_CAMERA_TYPE_ALIASES = {
    "usb": CameraType.USB.value,
    "local": CameraType.USB.value,
    "webcam": CameraType.USB.value,
    "rtsp": CameraType.RTSP.value,
    "rtsps": CameraType.RTSP.value,
    "onvif": CameraType.RTSP.value,
    "http": CameraType.HTTP.value,
    "https": CameraType.HTTP.value,
    "mjpeg": CameraType.HTTP.value,
    "ip": CameraType.IP.value,
    "ipc": CameraType.IP.value,
    "network": CameraType.NETWORK.value,
    "net": CameraType.NETWORK.value,
    "simulated": CameraType.SIMULATED.value,
    "simulation": CameraType.SIMULATED.value,
    "sim": CameraType.SIMULATED.value,
    "fake": CameraType.SIMULATED.value,
}

# 需要真实取流的类型集合（非仿真）。
_REAL_CAMERA_TYPES = frozenset(
    {
        CameraType.USB.value,
        CameraType.RTSP.value,
        CameraType.HTTP.value,
        CameraType.IP.value,
        CameraType.NETWORK.value,
    }
)


def normalize_camera_type(value) -> str:
    """把任意来源的类型写法归一化为标准值；无法识别时返回 'simulated'。"""
    if value is None:
        return CameraType.SIMULATED.value
    raw = getattr(value, "value", value)
    key = str(raw).strip().lower()
    return _CAMERA_TYPE_ALIASES.get(key, CameraType.SIMULATED.value)


def is_real_camera_type(value) -> bool:
    """该类型是否应尝试打开真实摄像头（而非直接走仿真画面）。"""
    return normalize_camera_type(value) in _REAL_CAMERA_TYPES


def infer_camera_type(source) -> str:
    """按来源串推断类型：rtsp:// → rtsp，http(s):// → http，纯数字 → usb，否则仿真。"""
    s = str(source or "").strip().lower()
    if not s:
        return CameraType.SIMULATED.value
    if s.startswith("rtsp://") or s.startswith("rtsps://"):
        return CameraType.RTSP.value
    if s.startswith("http://") or s.startswith("https://"):
        return CameraType.HTTP.value
    if s.isdigit():
        return CameraType.USB.value
    return CameraType.SIMULATED.value


class RoiRect(BaseModel):
    """归一化 ROI 矩形（第二期 G6）：左上角 (x, y) + 尺寸 (w, h)，取值 0~1。"""

    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)
    w: float = Field(..., gt=0.0, le=1.0)
    h: float = Field(..., gt=0.0, le=1.0)


MASK_MARK = ":***@"  # H3：脱敏标记（user:***@host）；亦用于识别"未修改"的回传值


def mask_source(source: str) -> str:
    """脱敏取流地址中的密码（第三期 1.2/H3）：rtsp://user:pass@host → rtsp://user:***@host。

    - 无凭据（无 userinfo）原样返回；仅用户名无密码时保留用户名；
    - 解析失败一律退化为 "***"，绝不原样吐回可能含密码的字符串。
    """
    if not source:
        return source
    try:
        from urllib.parse import urlparse, urlunparse

        p = urlparse(source)
        if not p.username:
            return source
        host = p.hostname or ""
        if ":" in host:  # IPv6 字面量
            host = f"[{host}]"
        if p.port:
            host = f"{host}:{p.port}"
        userinfo = p.username + (":***" if p.password else "")
        return urlunparse(p._replace(netloc=f"{userinfo}@{host}"))
    except Exception:  # pragma: no cover - 防御性兜底
        return "***"


def mask_camera(info: "CameraInfo") -> "CameraInfo":
    """返回脱敏副本（不改动内部对象）：source 替换为脱敏值，仅供 API 响应使用。

    内部链路（frame_hub / inspection_engine / camera_capture）仍读原始 source 取流。
    """
    return info.model_copy(update={"source": mask_source(info.source)})


class CameraInfo(BaseModel):
    id: str
    name: str
    type: CameraType = CameraType.SIMULATED
    source: str = "0"
    enabled: bool = True
    status: str = "unknown"  # online / offline / unknown
    resolution: Optional[str] = None
    roi: List[RoiRect] = []  # G6：检测区域（归一化矩形列表），空表示全画面

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_masked(self) -> str:
        """脱敏地址（rtsp://user:***@host）：随序列化自动携带，前端展示专用。"""
        return mask_source(self.source)


class SystemHealth(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    status: str = "healthy"  # healthy / warning / critical
    psutil_available: bool = True


class CameraRuntimeStatus(BaseModel):
    """单摄像头运行时状态（第二期 G5 多摄并发）。"""

    camera_id: str
    total_processed: int = 0


class InspectionStatus(BaseModel):
    running: bool = False
    total_processed: int = 0
    active_camera_id: Optional[str] = None
    active_batch_id: Optional[str] = None
    running_cameras: List[CameraRuntimeStatus] = []  # G5：每摄任务与分摄计数
    last_result: Optional[DetectionResult] = None
    detector_mode: str = "simulation"  # simulation / yolo


# ---------- 认证与权限 ----------
class UserRole(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class User(BaseModel):
    id: Optional[int] = None
    username: str
    display_name: str = ""
    role: UserRole = UserRole.VIEWER
    disabled: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class LoginRequest(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User


# ---------- 告警 ----------
class AlertMetric(str, Enum):
    DEFECT_RATE = "defect_rate"
    DEFECT_COUNT = "defect_count"
    PROCESSING_TIME = "processing_time_ms"


class AlertOperator(str, Enum):
    GT = "gt"
    GE = "ge"
    LT = "lt"
    LE = "le"


class AlertRule(BaseModel):
    id: Optional[int] = None
    name: str
    metric: AlertMetric = AlertMetric.DEFECT_RATE
    operator: AlertOperator = AlertOperator.GT
    threshold: float = 0.5
    scope: str = "all"  # all 或具体 camera_id
    enabled: bool = True
    notify_email: Optional[str] = None
    # 多渠道通知（第二期 G3）：webhook 渠道 URL 与类型
    webhook_url: Optional[str] = None
    webhook_type: Optional[str] = None  # generic / dingtalk / feishu / wecom
    # 告警冷却与聚合（第三期 2.1）：cooldown_seconds=0 表示不冷却（旧行为）
    cooldown_seconds: int = Field(default=0, ge=0, le=7 * 86400)
    silence_until: Optional[str] = None  # 运营静默：该 UTC 时刻前完全跳过评估
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class AlertEvent(BaseModel):
    id: Optional[int] = None
    rule_id: Optional[int] = None
    camera_id: str = ""
    message: str = ""
    severity: str = "warning"  # warning / critical
    value: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    acknowledged: bool = False
    notified: bool = False
    # G2 人工判定字段（与 alert_events 表列对应；response_model 需完整保留，防字段被吞）
    result_id: Optional[int] = None
    verdict: str = "pending"  # pending / confirmed / false_positive / missed
    remark: Optional[str] = ""
    judged_by: Optional[str] = None
    judged_at: Optional[str] = None
    # 冷却聚合（第三期 2.1）：冷却窗口内重复命中聚合计数与恢复标记
    repeat_count: int = 0
    recovered: bool = False
    recovered_at: Optional[str] = None


class AlertEventPage(BaseModel):
    """告警事件分页响应（G9）。"""

    page: int
    page_size: int
    total: int
    items: List[AlertEvent]


class AckResult(BaseModel):
    ok: bool
    acknowledged: int


class InspectionStartResult(BaseModel):
    """检测启动响应（G5 多摄）。"""

    status: str
    active_camera_id: Optional[str] = None
    active_batch_id: Optional[str] = None
    running_cameras: List[CameraRuntimeStatus] = []


class InspectionStopResult(BaseModel):
    """检测停止响应（G5 支持单停/全停）。"""

    status: str
    running: bool = False
    running_cameras: List[CameraRuntimeStatus] = []


class ActiveCameraResult(BaseModel):
    ok: bool
    active_camera_id: str


# ---------- 自定义瑕疵类型 ----------
class DefectTypeConfig(BaseModel):
    name: str
    color: str = "#f56c6c"
    enabled: bool = True


# ---------- 模型版本 ----------
class ModelVersion(BaseModel):
    id: Optional[int] = None
    name: str
    version: str = "1.0.0"
    file_path: str = ""
    metric: float = 0.0  # mAP / accuracy
    active: bool = False
    description: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ---------- 通用分页响应 ----------
class PageEnvelope(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[dict] = Field(default_factory=list)


# ---------- 报表聚合 ----------
class TrendPoint(BaseModel):
    bucket: str
    total: int
    defect_count: int
    defect_rate: float


class TypeShare(BaseModel):
    class_name: str
    count: int


class ReportSummary(BaseModel):
    total: int
    defect_count: int
    defect_rate: float
    avg_processing_ms: float
    by_type: List[TypeShare] = Field(default_factory=list)
    trend: List[TrendPoint] = Field(default_factory=list)


# ---------- 批次管理（第二期 G4） ----------
class BatchInfo(BaseModel):
    id: Optional[int] = None
    batch_no: str
    product: str = ""
    started_at: str = ""
    ended_at: Optional[str] = None
    note: str = ""


class BatchReport(BaseModel):
    batch_id: str
    total: int
    defect_count: int
    total_count: int
    defect_rate: float
    defect_frame_rate: float
    avg_processing_ms: float
    by_type: List[TypeShare] = Field(default_factory=list)


# ---------- 备份与恢复（第二期 G7a） ----------
class BackupInfo(BaseModel):
    path: str
    filename: str
    size_bytes: int
    created_at: str
