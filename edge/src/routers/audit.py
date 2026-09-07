"""审计日志查询接口（L3）：供管理员查看管理类操作流水。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import get_current_user, require_admin
from ..models import User

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(get_current_user)])


@router.get("")
def list_audit(request: Request, _admin: User = Depends(require_admin), page: int = 1, page_size: int = 50):
    return {
        "items": request.app.state.audit.recent(page=page, page_size=page_size),
        "page": page,
        "page_size": page_size,
    }
