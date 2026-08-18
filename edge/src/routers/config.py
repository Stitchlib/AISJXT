from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..auth import get_current_user
from ..models import DefectTypeConfig, User

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(get_current_user)])


class ConfigUpdate(BaseModel):
    confidence_threshold: Optional[float] = None
    iou_threshold: Optional[float] = None
    enable_simulation: Optional[bool] = None
    model_path: Optional[str] = None
    push_interval_frames: Optional[int] = None
    # 邮件/告警
    smtp_enabled: Optional[bool] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_mode: Optional[str] = None
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    smtp_from: Optional[str] = None
    # 自定义瑕疵类型
    defect_types: Optional[List[DefectTypeConfig]] = None


@router.get("")
def get_config(request: Request):
    return request.app.state.cm.get().model_dump()


@router.put("")
def update_config(payload: ConfigUpdate, request: Request):
    updated = request.app.state.cm.update(**payload.model_dump(exclude_unset=True))
    return updated.model_dump()
