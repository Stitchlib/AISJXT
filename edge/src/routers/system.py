"""系统运维：SQLite 备份与恢复（第二期 G7a）。

- POST /system/backup：手动触发一次在线备份（仅 admin），返回备份文件信息
- GET  /system/backups：列出已有备份（仅 admin）
- 每日定时备份与超额清理由 main._backup_loop 驱动（保留最近 N 份，N 默认 7 可配）
- 恢复流程：停服后用备份文件替换 data/inspection.db（WAL 下备份已是完整一致快照）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import get_current_user, require_admin
from ..models import BackupInfo, User

router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(get_current_user)])


@router.post("/backup", response_model=BackupInfo)
def trigger_backup(request: Request, _admin: User = Depends(require_admin)):
    db = request.app.state.db
    cfg = request.app.state.cm.get()
    dest = db.backup(dest_path=cfg.backup_dir)
    info = db.list_backups(cfg.backup_dir)
    item = next((b for b in info if b["path"] == dest), None)
    # 触发后即做一次超额清理，保持落盘整洁
    try:
        db.prune_backups(cfg.backup_retention, cfg.backup_dir)
    except Exception:
        pass
    # 审计（L3 延续）
    try:
        request.app.state.audit.record(
            actor=_admin.username, action="system.backup", target=dest,
            ip=request.client.host if request.client else "",
        )
    except Exception:
        pass
    if item is None:
        raise HTTPException(status_code=500, detail="备份已生成但读取元信息失败")
    return BackupInfo(**item)


@router.get("/backups", response_model=list[BackupInfo])
def list_backups(request: Request, _admin: User = Depends(require_admin)):
    cfg = request.app.state.cm.get()
    return [BackupInfo(**b) for b in request.app.state.db.list_backups(cfg.backup_dir)]
