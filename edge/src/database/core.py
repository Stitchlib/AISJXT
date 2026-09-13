"""数据库核心：单持久连接、建表 DDL、版本化迁移、审计、在线备份。

仅持有【一个】持久连接（check_same_thread=False），由 _lock 串行化所有访问，
避免逐行 sqlite3.connect 的昂贵开销（沙箱/机械盘下每行可达数十毫秒）。
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from ..models import utc_iso


class DatabaseCore:
    """连接/DDL/迁移/审计/备份 mixin（与各域 mixin 组合为门面 Database）。"""

    def __init__(self, db_path: str = "data/inspection.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._current_schema_version: list = []
        # 持久连接：复用避免逐行重连开销；锁保证线程安全
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # 边缘设备优化：WAL 避免读写互斥；synchronous=NORMAL 仅检查点 fsync，
        # 单条提交成本大幅下降（崩溃最多丢失最近一个事务，不会损坏库）。
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    @contextmanager
    def _conn_cm(self):
        with self._lock:
            yield self._conn

    def _init_schema(self) -> None:
        with self._conn_cm() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS detection_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    camera_id TEXT,
                    image_path TEXT,
                    defects TEXT,
                    total_count INTEGER,
                    defect_count INTEGER,
                    defect_rate REAL,
                    processing_time_ms REAL,
                    is_simulation INTEGER,
                    metric_version INTEGER DEFAULT 2
                )
                """
            )
            # 查询性能索引（M3）：按摄像头+时间过滤/排序、以及按时间清理是最高频操作。
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_detection_camera_ts "
                "ON detection_results(camera_id, timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_detection_ts ON detection_results(timestamp)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    display_name TEXT,
                    role TEXT,
                    disabled INTEGER,
                    created_at TEXT,
                    salt TEXT,
                    password_hash TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT, metric TEXT, operator TEXT, threshold REAL,
                    scope TEXT, enabled INTEGER, notify_email TEXT, created_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_id INTEGER, camera_id TEXT, message TEXT, severity TEXT,
                    value REAL, timestamp TEXT, acknowledged INTEGER, notified INTEGER,
                    result_id INTEGER,
                    verdict TEXT DEFAULT 'pending', remark TEXT, judged_by TEXT, judged_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT, version TEXT, file_path TEXT, metric REAL,
                    active INTEGER, description TEXT, created_at TEXT
                )
                """
            )
            # 审计日志（L3）：记录管理类操作 who/what/when/ip，供事后追溯与合规审计。
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor TEXT,
                    action TEXT,
                    target TEXT,
                    detail TEXT,
                    ip TEXT,
                    timestamp TEXT
                )
                """
            )
            # 聚合计数器（M2 性能验收）：增量维护，查询时 O(1) 读取，避免百万行全表扫描。
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agg_counters (
                    id INTEGER PRIMARY KEY CHECK (id=1),
                    total INTEGER DEFAULT 0,
                    defect_count_sum INTEGER DEFAULT 0,
                    total_count_sum INTEGER DEFAULT 0,
                    processing_time_sum REAL DEFAULT 0,
                    sim_count INTEGER DEFAULT 0,
                    defect_frames INTEGER DEFAULT 0,
                    trusted_records INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS agg_type_shares (class_name TEXT PRIMARY KEY, cnt INTEGER DEFAULT 0)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS agg_trend (bucket TEXT PRIMARY KEY, total INTEGER DEFAULT 0, defect_frames INTEGER DEFAULT 0)"
            )
            # 批次/工单（第二期 G4）：生产批次维度追溯，batch_id 为空表示未绑定批次
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_no TEXT UNIQUE,
                    product TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    note TEXT
                )
                """
            )
            conn.execute("INSERT OR IGNORE INTO agg_counters(id) VALUES(1)")
            conn.commit()
        self._migrate()

    # ---------- schema 版本化迁移（第二期 G7b） ----------
    SCHEMA_VERSION_TABLE = "schema_version"

    def _mg_metric_version(self, conn) -> None:
        """第一期口径迁移：旧库补 metric_version 列；历史含随机数的仿真标记为口径 1（不可信）。"""
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(detection_results)").fetchall()}
        if "metric_version" not in cols:
            conn.execute("ALTER TABLE detection_results ADD COLUMN metric_version INTEGER DEFAULT 2")
        try:
            conn.execute(
                "UPDATE detection_results SET metric_version=1 WHERE metric_version IS NULL AND is_simulation=1"
            )
        except Exception:
            pass

    def _mg_alert_verdict(self, conn) -> None:
        """第二期 G2：告警事件补判定列，默认 pending 待判定。"""
        acols = {r["name"] for r in conn.execute("PRAGMA table_info(alert_events)").fetchall()}
        for col_def in (
            ("result_id", "INTEGER"),
            ("verdict", "TEXT DEFAULT 'pending'"),
            ("remark", "TEXT"),
            ("judged_by", "TEXT"),
            ("judged_at", "TEXT"),
        ):
            if col_def[0] not in acols:
                conn.execute(f"ALTER TABLE alert_events ADD COLUMN {col_def[0]} {col_def[1]}")

    def _mg_batch_id(self, conn) -> None:
        """第二期 G4：检测记录补 batch_id 列（兼容 NULL，未绑定批次即为空）。"""
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(detection_results)").fetchall()}
        if "batch_id" not in cols:
            conn.execute("ALTER TABLE detection_results ADD COLUMN batch_id TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_detection_batch ON detection_results(batch_id)"
            )

    def _mg_webhook(self, conn) -> None:
        """第二期 G3：告警规则补 webhook 渠道字段。"""
        acols = {r["name"] for r in conn.execute("PRAGMA table_info(alert_rules)").fetchall()}
        if "webhook_url" not in acols:
            conn.execute("ALTER TABLE alert_rules ADD COLUMN webhook_url TEXT")
        if "webhook_type" not in acols:
            conn.execute("ALTER TABLE alert_rules ADD COLUMN webhook_type TEXT")

    def _mg_alert_cooling(self, conn) -> None:
        """第三期 2.1：告警冷却与聚合。

        - alert_rules 补 cooldown_seconds（默认 0=不冷却，行为与旧版完全兼容）与
          silence_until（运营静默窗口，绝对 UTC 时间戳，之前完全跳过评估）；
        - alert_events 补 repeat_count（冷却窗口内重复命中聚合计数）、
          recovered/recovered_at（状态恢复标记，恢复通知依据）；
        - 补 (rule_id, camera_id, id) 索引：冷却判定取"该规则+摄像头最新事件"与
          恢复查询走索引，避免逐帧全表扫描。
        """
        rcols = {r["name"] for r in conn.execute("PRAGMA table_info(alert_rules)").fetchall()}
        if "cooldown_seconds" not in rcols:
            conn.execute("ALTER TABLE alert_rules ADD COLUMN cooldown_seconds INTEGER DEFAULT 0")
        if "silence_until" not in rcols:
            conn.execute("ALTER TABLE alert_rules ADD COLUMN silence_until TEXT")
        ecols = {r["name"] for r in conn.execute("PRAGMA table_info(alert_events)").fetchall()}
        if "repeat_count" not in ecols:
            conn.execute("ALTER TABLE alert_events ADD COLUMN repeat_count INTEGER DEFAULT 0")
        if "recovered" not in ecols:
            conn.execute("ALTER TABLE alert_events ADD COLUMN recovered INTEGER DEFAULT 0")
        if "recovered_at" not in ecols:
            conn.execute("ALTER TABLE alert_events ADD COLUMN recovered_at TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_alert_rule_cam "
            "ON alert_events(rule_id, camera_id, id)"
        )

    def _migrate(self) -> None:
        """按序执行幂等迁移并记录当前 schema 版本（G7b）。

        迁移函数均为"存在则跳过"的幂等方式，重复启动不会重复执行；
        任一迁移失败则整体回滚并报错，保留原库（绝不半个状态）。
        """
        with self._conn_cm() as conn:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.SCHEMA_VERSION_TABLE} "
                f"(version TEXT PRIMARY KEY, applied_at TEXT)"
            )
            applied = {
                r["version"]
                for r in conn.execute(f"SELECT version FROM {self.SCHEMA_VERSION_TABLE}").fetchall()
            }
            # 迁移链（按序执行；新增迁移追加到末尾，旧库启动后自动补齐到最新版）
            migrations = [
                ("001_metric_version", self._mg_metric_version),
                ("002_alert_verdict", self._mg_alert_verdict),
                ("003_batch_id", self._mg_batch_id),
                ("004_webhook", self._mg_webhook),
                ("005_alert_cooling", self._mg_alert_cooling),
            ]
            for name, fn in migrations:
                if name in applied:
                    continue
                try:
                    fn(conn)
                except Exception as e:
                    conn.rollback()
                    raise RuntimeError(f"schema migration failed at {name}: {e}")
                conn.execute(
                    f"INSERT OR IGNORE INTO {self.SCHEMA_VERSION_TABLE}(version, applied_at) VALUES(?,?)",
                    (name, utc_iso()),
                )
            # 历史库迁移：计数器为空但已有检测数据则全量重算补齐（非 schema 变更，失败不影响启动）
            try:
                _cur = conn.execute("SELECT total FROM agg_counters WHERE id=1").fetchone()
                _cnt = conn.execute("SELECT COUNT(*) FROM detection_results").fetchone()[0]
                if (_cur is None or (_cur[0] or 0) == 0) and _cnt > 0:
                    self._recompute_aggregates_conn(conn)
            except Exception:
                pass
            conn.commit()
        self._current_schema_version = [name for name, _ in migrations]

    def get_schema_version(self) -> dict:
        """返回当前 schema 版本信息（供启动日志与运维排障）。"""
        versions = getattr(self, "_current_schema_version", [])
        return {
            "current": versions[-1] if versions else None,
            "applied": list(versions),
            "count": len(versions),
        }

    # ---------- 审计日志 ----------
    def insert_audit(self, actor: str, action: str, target: str = "", detail: str = "", ip: str = "") -> int:
        with self._conn_cm() as conn:
            cur = conn.execute(
                "INSERT INTO audit_logs (actor, action, target, detail, ip, timestamp) VALUES (?,?,?,?,?,?)",
                (actor, action, target, detail, ip, utc_iso()),
            )
            conn.commit()
            return cur.lastrowid

    def list_audit(self, page: int = 1, page_size: int = 50) -> List[dict]:
        with self._conn_cm() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ? OFFSET ?",
                (page_size, (page - 1) * page_size),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- 备份与恢复（第二期 G7a） ----------
    def backup(self, dest_path: str | None = None) -> str:
        """在线备份当前库（sqlite3 备份 API，自动 checkpoint WAL）。

        在持锁状态下进行，期间不阻塞自身写入（WAL 读一致快照）；
        目标文件名默认 inspection_<UTC>.db，落至 data/backups/。
        """
        if dest_path is None:
            default_dir = Path(self.db_path).parent / "backups"
            default_dir.mkdir(parents=True, exist_ok=True)
            dest_path = str(
                default_dir
                / f"inspection_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db"
            )
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn_cm() as conn:
            target = sqlite3.connect(dest_path)
            try:
                conn.backup(target)  # 源库 -> 目标库，得到一致快照
            finally:
                target.close()
        return dest_path

    def list_backups(self, backup_dir: str | None = None) -> List[dict]:
        d = Path(backup_dir) if backup_dir else (Path(self.db_path).parent / "backups")
        if not d.exists():
            return []
        out = []
        for f in d.glob("*.db"):
            try:
                st = f.stat()
                out.append(
                    {
                        "path": str(f),
                        "filename": f.name,
                        "size_bytes": st.st_size,
                        "created_at": datetime.fromtimestamp(st.st_ctime, timezone.utc).isoformat(),
                    }
                )
            except OSError:
                continue
        out.sort(key=lambda x: x["filename"], reverse=True)
        return out

    def prune_backups(self, retention: int, backup_dir: str | None = None) -> int:
        """保留最近 retention 份（按文件名时间序），删除更旧的。返回删除数。"""
        if not retention or retention <= 0:
            return 0
        items = self.list_backups(backup_dir)
        if len(items) <= retention:
            return 0
        to_delete = sorted(items, key=lambda x: x["filename"])[:-retention]
        removed = 0
        for it in to_delete:
            try:
                Path(it["path"]).unlink()
                removed += 1
            except OSError:
                continue
            except SystemExit:
                # 环境删除钩子（safe-delete guard）可能抛 SystemExit(1)，
                # 其继承自 BaseException，不接住会穿透并炸掉整个服务进程。
                # 删除失败不应影响主流程：跳过该文件，下次清理再试。
                continue
        return removed
