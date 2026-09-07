"""审计日志：记录管理类操作（登录、配置变更、用户增删、模型激活等）。

通过 app.state.audit 暴露，供路由层调用 record()；底层持久化到 audit_logs 表。
"""
from __future__ import annotations

import logging
from typing import List

from .database import Database

logger = logging.getLogger("audit")


class AuditLogger:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(
        self,
        actor: str,
        action: str,
        target: str = "",
        detail: str = "",
        ip: str = "",
    ) -> None:
        try:
            self._db.insert_audit(actor=actor, action=action, target=target, detail=detail, ip=ip)
        except Exception as e:  # 审计失败绝不阻断主流程
            logger.warning("审计日志写入失败: %s", e)

    def recent(self, page: int = 1, page_size: int = 50) -> List[dict]:
        return self._db.list_audit(page=page, page_size=page_size)


def get_audit_logger(request) -> AuditLogger:
    return request.app.state.audit
