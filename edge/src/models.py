"""模块间数据契约（Schema）。

所有跨模块数据交换都通过这些 Pydantic 模型完成，确保类型安全与一致性。
前端、WebSocket 推送、数据库持久化、API 响应共用同一套结构。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


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
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    camera_id: str = "cam_sim"
    image_path: Optional[str] = None
    defects: List[Defect] = Field(default_factory=list)
    total_count: int = 0
    defect_count: int = 0
    defect_rate: float = 0.0
    processing_time_ms: float = 0.0
    is_simulation: bool = False

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
        }


class CameraType(str, Enum):
    USB = "usb"
    IP = "ip"
    NETWORK = "network"
    SIMULATED = "simulated"


class CameraInfo(BaseModel):
    id: str
    name: str
    type: CameraType = CameraType.SIMULATED
    source: str = "0"
    enabled: bool = True
    status: str = "unknown"  # online / offline / unknown
    resolution: Optional[str] = None


class SystemHealth(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    status: str = "healthy"  # healthy / warning / critical
    psutil_available: bool = True


class InspectionStatus(BaseModel):
    running: bool = False
    total_processed: int = 0
    active_camera_id: Optional[str] = None
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
