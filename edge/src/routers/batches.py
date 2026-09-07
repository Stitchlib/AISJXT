"""批次/工单管理（第二期 G4）。

- 新建/结束批次：operator 及以上
- 批次列表/详情：登录即可
- 结束批次会同步清空检测引擎的当前绑定批次，避免后续记录错误继承已结束批次
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import get_current_user, require_operator
from ..models import BatchInfo, User

router = APIRouter(prefix="/batches", tags=["batches"], dependencies=[Depends(get_current_user)])


class BatchCreate(BaseModel):
    batch_no: str
    product: Optional[str] = None
    note: Optional[str] = None


@router.post("", status_code=201, response_model=BatchInfo)
def create_batch(body: BatchCreate, request: Request, _op: User = Depends(require_operator)):
    db = request.app.state.db
    try:
        bid = db.create_batch(body.batch_no, product=body.product or "", note=body.note or "")
    except Exception as e:
        # 唯一约束冲突等
        raise HTTPException(status_code=409, detail=f"批次创建失败（batch_no 可能已存在）: {e}")
    row = db.get_batch(body.batch_no)
    # 审计（L3 延续）
    try:
        request.app.state.audit.record(
            actor=_op.username, action="batch.create", target=body.batch_no,
            detail=f"id={bid} product={body.product or ''}",
            ip=request.client.host if request.client else "",
        )
    except Exception:
        pass
    return BatchInfo(**row)


@router.get("", response_model=list[BatchInfo])
def list_batches(request: Request):
    return [BatchInfo(**r) for r in request.app.state.db.list_batches()]


@router.get("/{batch_id}", response_model=BatchInfo)
def get_batch(batch_id: str, request: Request):
    row = request.app.state.db.get_batch(batch_id)
    if not row:
        raise HTTPException(status_code=404, detail="批次不存在")
    return BatchInfo(**row)


@router.post("/{batch_id}/end", response_model=BatchInfo)
def end_batch(batch_id: str, request: Request, _op: User = Depends(require_operator)):
    db = request.app.state.db
    if not db.get_batch(batch_id):
        raise HTTPException(status_code=404, detail="批次不存在")
    if not db.end_batch(batch_id):
        raise HTTPException(status_code=400, detail="结束批次失败")
    # 同步清空检测引擎的当前绑定批次（若正绑定该批次）
    try:
        request.app.state.engine.clear_active_batch(batch_id)
    except Exception:
        pass
    # 审计（L3 延续）
    try:
        request.app.state.audit.record(
            actor=_op.username, action="batch.end", target=batch_id,
            ip=request.client.host if request.client else "",
        )
    except Exception:
        pass
    return BatchInfo(**db.get_batch(batch_id))
