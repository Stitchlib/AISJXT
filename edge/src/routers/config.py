from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import get_current_user, require_admin
from ..models import DefectTypeConfig, User

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(get_current_user)])


class ConfigUpdate(BaseModel):
    confidence_threshold: Optional[float] = None
    iou_threshold: Optional[float] = None
    enable_simulation: Optional[bool] = None
    model_path: Optional[str] = None
    push_interval_frames: Optional[int] = None
    # 缺陷图片留存（第二期 G1）
    save_image_mode: Optional[str] = None
    image_quota_gb: Optional[float] = None
    image_retention_days: Optional[int] = None
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
    # 备份与恢复（第二期 G7a）
    backup_dir: Optional[str] = None
    backup_retention: Optional[int] = None


# H1：敏感字段白名单脱敏视图，绝不回显 secret_key 与明文密码。
_SENSITIVE_FIELDS = {"secret_key"}
_MASKED_FIELDS = {"smtp_pass"}


def _public_config(cfg) -> dict:
    data = cfg.model_dump()
    for field in _SENSITIVE_FIELDS:
        data.pop(field, None)
    for field in _MASKED_FIELDS:
        # 仅在确有值时以掩码回显，避免泄露；空值保持空字符串
        if data.get(field):
            data[field] = "***"
    return data


@router.get("")
def get_config(request: Request):
    return _public_config(request.app.state.cm.get())


@router.put("")
def update_config(
    payload: ConfigUpdate,
    request: Request,
    _admin: User = Depends(require_admin),  # M5：仅管理员可修改配置
):
    changes = payload.model_dump(exclude_unset=True)
    # 密码以空串提交时视为"不修改"，避免误清空 SMTP 凭据（H1/M5 配套）
    if changes.get("smtp_pass") == "":
        changes.pop("smtp_pass", None)
    # 图片留存模式白名单校验（第二期 G1）
    if "save_image_mode" in changes and changes["save_image_mode"] not in ("none", "defect_only", "all", "sample"):
        raise HTTPException(status_code=400, detail="save_image_mode 必须为 none/defect_only/all/sample")
    updated = request.app.state.cm.update(**changes)
    # 审计（L3）
    try:
        request.app.state.audit.record(
            actor=_admin.username, action="config.update", target="system",
            detail=f"更新字段: {', '.join(changes.keys())}",
            ip=request.client.host if request.client else "",
        )
    except Exception:
        pass
    return _public_config(updated)
