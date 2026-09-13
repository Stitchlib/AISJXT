"""检测结果持久化层（SQLite，标准库实现，零额外依赖）。

第三期 3.4 按域拆包：原 1000+ 行单文件拆为
- core.py：连接、建表 DDL、版本化迁移、审计、在线备份
- results.py：检测结果写入/查询、增量聚合统计、CSV 导出、保留期清理
- alerts.py：告警规则/事件、冷却聚合、人工判定、训练样本导出
- batches.py：批次生命周期与批次报表
- users_models.py：用户 CRUD 与模型版本登记

Database 门面 API 签名保持零变更（mixin 组合），调用方仍以
`from src.database import Database` 使用。
"""
from __future__ import annotations

from .alerts import AlertsMixin
from .batches import BatchesMixin
from .core import DatabaseCore
from .results import ResultsMixin
from .users_models import UsersModelsMixin

__all__ = ["Database"]


class Database(DatabaseCore, ResultsMixin, AlertsMixin, BatchesMixin, UsersModelsMixin):
    """持久化门面：组合各域 mixin，对外暴露与历史单文件版本一致的全部方法。"""
