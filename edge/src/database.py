"""检测结果持久化层（SQLite，标准库实现，零额外依赖）。

职责：
- 建表与写入（由 inspection_engine 调用）
- 分页/条件查询（由 detection router 调用）
- 统计聚合（dashboard / 报表）
- CSV/批量导入导出（溯源与离线分析）

性能要点：
- 仅持有【一个】持久连接（check_same_thread=False），由 _lock 串行化所有访问，
  避免逐行 sqlite3.connect 的昂贵开销（沙箱/机械盘下每行可达数十毫秒）。
- 批量写入提供 executemany 单事务路径，满足高吞吐与离线导入场景。
"""
from __future__ import annotations

import csv
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple

from .models import utc_iso


class Database:
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

    # ---------- 检测结果写入 ----------
    def insert_result(self, row: dict) -> int:
        with self._conn_cm() as conn:
            cur = conn.execute(
                """
                INSERT INTO detection_results
                (timestamp, camera_id, image_path, defects, total_count,
                 defect_count, defect_rate, processing_time_ms, is_simulation, metric_version, batch_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["timestamp"],
                    row["camera_id"],
                    row.get("image_path"),
                    json.dumps(row.get("defects", []), ensure_ascii=False),
                    row["total_count"],
                    row["defect_count"],
                    row["defect_rate"],
                    row["processing_time_ms"],
                    int(row.get("is_simulation", False)),
                    int(row.get("metric_version", 2)),
                    row.get("batch_id"),
                ),
            )
            self._apply_bump(conn, row)
            conn.commit()
            return cur.lastrowid

    def bulk_insert_results(self, rows: List[dict]) -> int:
        """批量写入（单事务 executemany），用于离线导入/回填，显著降低 IO 开销。"""
        if not rows:
            return 0
        payload = [
            (
                r["timestamp"],
                r["camera_id"],
                r.get("image_path"),
                json.dumps(r.get("defects", []), ensure_ascii=False),
                r["total_count"],
                r["defect_count"],
                r["defect_rate"],
                r["processing_time_ms"],
                int(r.get("is_simulation", False)),
                int(r.get("metric_version", 2)),
                r.get("batch_id"),
            )
            for r in rows
        ]
        with self._conn_cm() as conn:
            conn.executemany(
                """
                INSERT INTO detection_results
                (timestamp, camera_id, image_path, defects, total_count,
                 defect_count, defect_rate, processing_time_ms, is_simulation, metric_version, batch_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                payload,
            )
            for r in rows:
                self._apply_bump(conn, r)
            conn.commit()
            return len(payload)

    def query_results(
        self,
        page: int = 1,
        page_size: int = 20,
        camera_id: str | None = None,
        defect_only: bool = False,
        start: str | None = None,
        end: str | None = None,
        batch_id: str | None = None,
    ) -> Tuple[List[dict], int]:
        clauses = []
        params: list = []
        if camera_id:
            clauses.append("camera_id=?")
            params.append(camera_id)
        if batch_id:
            clauses.append("batch_id=?")
            params.append(batch_id)
        if defect_only:
            clauses.append("defect_count>0")
        if start:
            clauses.append("timestamp>=?")
            params.append(start)
        if end:
            clauses.append("timestamp<=?")
            params.append(end)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn_cm() as conn:
            rows = conn.execute(
                f"SELECT * FROM detection_results{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [page_size, (page - 1) * page_size],
            ).fetchall()
            # 无过滤时直接读取增量维护的总计数（O(1)），避免百万行 COUNT(*) 全表扫描；
            # 带过滤条件时走索引 COUNT(*)，仍可接受。
            if where == "":
                total = conn.execute(
                    "SELECT total FROM agg_counters WHERE id=1"
                ).fetchone()[0] or 0
            else:
                total = conn.execute(
                    f"SELECT COUNT(*) FROM detection_results{where}", params
                ).fetchone()[0]
            items = []
            for r in rows:
                d = dict(r)
                try:
                    d["defects"] = json.loads(d["defects"]) if d["defects"] else []
                except Exception:
                    d["defects"] = []
                items.append(d)
            return items, total

    # ---------- 聚合计数（M2 性能验收：增量维护，O(1) 读取） ----------
    def _apply_bump(self, conn, row: dict) -> None:
        """在已有事务内（conn 已持锁）增量更新聚合计数器，零全表扫描。"""
        dc = int(row.get("defect_count", 0) or 0)
        tc = int(row.get("total_count", 0) or 0)
        pt = float(row.get("processing_time_ms", 0.0) or 0.0)
        sim = int(row.get("is_simulation", False))
        mv = int(row.get("metric_version", 2))
        ts = row.get("timestamp") or ""
        defects = row.get("defects", [])
        if isinstance(defects, str):
            try:
                defects = json.loads(defects)
            except Exception:
                defects = []
        bucket = ts[:10] if ts else "unknown"
        class_names = [
            d.get("class_name")
            for d in defects
            if isinstance(d, dict) and d.get("class_name")
        ]
        conn.execute(
            "UPDATE agg_counters SET total=total+1, defect_count_sum=defect_count_sum+?, "
            "total_count_sum=total_count_sum+?, processing_time_sum=processing_time_sum+?, "
            "sim_count=sim_count+?, defect_frames=defect_frames+?, trusted_records=trusted_records+? "
            "WHERE id=1",
            (dc, tc, pt, sim, 1 if dc > 0 else 0, 1 if mv >= 2 else 0),
        )
        for cn in class_names:
            conn.execute(
                "INSERT INTO agg_type_shares(class_name, cnt) VALUES(?, 1) "
                "ON CONFLICT(class_name) DO UPDATE SET cnt=cnt+1",
                (cn,),
            )
        conn.execute(
            "INSERT INTO agg_trend(bucket, total, defect_frames) VALUES(?, 1, ?) "
            "ON CONFLICT(bucket) DO UPDATE SET total=total+1, defect_frames=defect_frames+?",
            (bucket, 1 if dc > 0 else 0, 1 if dc > 0 else 0),
        )

    def _recompute_aggregates_conn(self, conn) -> None:
        """基于 detection_results 全量重算聚合计数器（conn 已持锁，不自行提交）。"""
        conn.execute("DELETE FROM agg_type_shares")
        conn.execute("DELETE FROM agg_trend")
        conn.execute(
            "UPDATE agg_counters SET total=0, defect_count_sum=0, total_count_sum=0, "
            "processing_time_sum=0, sim_count=0, defect_frames=0, trusted_records=0 WHERE id=1"
        )
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(defect_count),0), COALESCE(SUM(total_count),0), "
            "COALESCE(AVG(processing_time_ms),0), "
            "COALESCE(SUM(CASE WHEN is_simulation THEN 1 ELSE 0 END),0), "
            "COALESCE(SUM(CASE WHEN defect_count>0 THEN 1 ELSE 0 END),0), "
            "COALESCE(SUM(CASE WHEN metric_version>=2 THEN 1 ELSE 0 END),0) "
            "FROM detection_results"
        ).fetchone()
        conn.execute(
            "UPDATE agg_counters SET total=?, defect_count_sum=?, total_count_sum=?, "
            "processing_time_sum=?, sim_count=?, defect_frames=?, trusted_records=? WHERE id=1",
            tuple(row),
        )
        conn.execute(
            "INSERT INTO agg_type_shares(class_name, cnt) "
            "SELECT json_extract(je.value, '$.class_name') AS class_name, COUNT(*) "
            "FROM detection_results, json_each(detection_results.defects) AS je "
            "WHERE json_extract(je.value, '$.class_name') IS NOT NULL GROUP BY class_name"
        )
        conn.execute(
            "INSERT INTO agg_trend(bucket, total, defect_frames) "
            "SELECT substr(timestamp,1,10) AS bucket, COUNT(*), "
            "COALESCE(SUM(CASE WHEN defect_count>0 THEN 1 ELSE 0 END),0) "
            "FROM detection_results GROUP BY bucket"
        )

    def recompute_aggregates(self) -> None:
        """全量重算聚合计数器（供离线导入回填 / 历史库迁移 / 保留期清理后调用）。"""
        with self._conn_cm() as conn:
            self._recompute_aggregates_conn(conn)
            conn.commit()

    def get_statistics(self) -> dict:
        # 直接读取增量维护的计数器（O(1)），百万行下仍 <1ms，满足 M2 验收 <500ms。
        # 缺陷率语义（H3 治理）：以"含缺陷的帧占比"口径统计 = 缺陷帧数 / 总帧数。
        with self._conn_cm() as conn:
            r = conn.execute(
                "SELECT total, defect_count_sum, total_count_sum, processing_time_sum, "
                "sim_count, defect_frames, trusted_records FROM agg_counters WHERE id=1"
            ).fetchone()
        total = r["total"] or 0
        defect_frames = r["defect_frames"] or 0
        defect_rate = round(defect_frames / total, 4) if total else 0.0
        avg_ms = round((r["processing_time_sum"] or 0) / total, 2) if total else 0.0
        return {
            "total": total,
            "defect_count": r["defect_count_sum"] or 0,
            "total_count": r["total_count_sum"] or 0,
            "defect_rate": defect_rate,
            "defect_frame_rate": defect_rate,  # 别名，明确口径
            "avg_processing_ms": avg_ms,
            "simulated_records": r["sim_count"] or 0,
            "trusted_records": r["trusted_records"] or 0,
        }

    def get_type_shares(self) -> List[dict]:
        # 读取增量维护的品类计数（O(小)），不再对百万行做 json_each 展开。
        with self._conn_cm() as conn:
            rows = conn.execute(
                "SELECT class_name, cnt AS count FROM agg_type_shares ORDER BY cnt DESC"
            ).fetchall()
        return [{"class_name": r["class_name"], "count": r["count"]} for r in rows]

    def get_trend(self, bucket: str = "day") -> List[dict]:
        # 读取增量维护的分桶计数（按日分桶）；缺陷率以"缺陷帧占比"口径计算。
        with self._conn_cm() as conn:
            rows = conn.execute(
                "SELECT bucket, total, defect_frames FROM agg_trend"
            ).fetchall()
        out = []
        for r in rows:
            total = r["total"] or 0
            df = r["defect_frames"] or 0
            out.append(
                {
                    "bucket": r["bucket"],
                    "total": total,
                    "defect_count": df,  # 桶内缺陷帧数
                    "defect_rate": round(df / total, 4) if total else 0.0,
                }
            )
        out.sort(key=lambda x: x["bucket"])
        return out

    def export_csv(self, path: str) -> str:
        # 流式写出（M2）：用游标逐行迭代，避免百万行全表载入内存。
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn_cm() as conn, open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "id", "timestamp", "camera_id", "defect_count", "total_count",
                    "defect_rate", "processing_time_ms", "is_simulation", "metric_version", "defects",
                ]
            )
            cur = conn.execute(
                "SELECT id, timestamp, camera_id, defect_count, total_count, "
                "defect_rate, processing_time_ms, is_simulation, metric_version, defects "
                "FROM detection_results ORDER BY id"
            )
            for r in cur:
                defects = r["defects"]
                try:
                    defects = json.loads(defects) if defects else []
                except Exception:
                    defects = []
                w.writerow(
                    [
                        r["id"], r["timestamp"], r["camera_id"], r["defect_count"],
                        r["total_count"], r["defect_rate"], r["processing_time_ms"],
                        r["is_simulation"], r["metric_version"],
                        json.dumps(defects, ensure_ascii=False),
                    ]
                )
        return path

    def cleanup_retention(self, retention_days: int) -> int:
        """清理超过保留期的检测数据（M3/L3 数据治理）。

        用 julianday(substr(timestamp,1,19)) 与'now'（UTC）比较，避免全表逐行 Python 处理。
        删除后重算聚合计数器，保证 dashboard/报表口径与剩余数据一致。
        返回被删除的行数。
        """
        if not retention_days or retention_days <= 0:
            return 0
        with self._conn_cm() as conn:
            cur = conn.execute(
                "DELETE FROM detection_results "
                "WHERE julianday(substr(timestamp,1,19)) < julianday('now', ?)",
                (f"-{int(retention_days)} days",),
            )
            deleted = cur.rowcount
            if deleted > 0:
                self._recompute_aggregates_conn(conn)
            conn.commit()
            return deleted

    # ---------- 用户 ----------
    def get_user_by_username(self, username: str) -> dict | None:
        with self._conn_cm() as conn:
            row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            return dict(row) if row else None

    def set_user_password_by_username(self, username: str, salt_hex: str, hash_hex: str) -> bool:
        with self._conn_cm() as conn:
            cur = conn.execute(
                "UPDATE users SET salt=?, password_hash=? WHERE username=?",
                (salt_hex, hash_hex, username),
            )
            conn.commit()
            return cur.rowcount > 0

    def get_user_by_id(self, user_id: int) -> dict | None:
        with self._conn_cm() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def create_user(self, username, display_name, role, salt_hex, hash_hex, disabled=False) -> int:
        with self._conn_cm() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, display_name, role, disabled, created_at, salt, password_hash) VALUES (?,?,?,?,?,?,?)",
                (username, display_name, role, int(disabled), utc_iso(), salt_hex, hash_hex),
            )
            conn.commit()
            return cur.lastrowid

    def list_users(self) -> List[dict]:
        with self._conn_cm() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT id,username,display_name,role,disabled,created_at FROM users ORDER BY id"
            ).fetchall()]

    def update_user(self, user_id: int, **fields) -> bool:
        allowed = ["display_name", "role", "disabled"]
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "disabled" in sets:
            sets["disabled"] = int(sets["disabled"])
        if not sets:
            return False
        cols = ", ".join(f"{k}=?" for k in sets)
        vals = [sets[k] for k in sets] + [user_id]
        with self._conn_cm() as conn:
            conn.execute(f"UPDATE users SET {cols} WHERE id=?", vals)
            conn.commit()
            return True

    def delete_user_by_id(self, user_id: int) -> bool:
        with self._conn_cm() as conn:
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            conn.commit()
            return True

    def count_users(self) -> int:
        with self._conn_cm() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # ---------- 告警规则 ----------
    def create_alert_rule(self, rule: dict) -> int:
        with self._conn_cm() as conn:
            cur = conn.execute(
                "INSERT INTO alert_rules (name,metric,operator,threshold,scope,enabled,notify_email,webhook_url,webhook_type,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    rule["name"], rule["metric"], rule["operator"], rule["threshold"],
                    rule["scope"], int(rule.get("enabled", True)), rule.get("notify_email"),
                    rule.get("webhook_url"), rule.get("webhook_type"),
                    rule.get("created_at", utc_iso()),
                ),
            )
            conn.commit()
            return cur.lastrowid

    def list_alert_rules(self) -> List[dict]:
        with self._conn_cm() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM alert_rules ORDER BY id DESC").fetchall()]

    def get_alert_rule(self, rid: int) -> dict | None:
        with self._conn_cm() as conn:
            row = conn.execute("SELECT * FROM alert_rules WHERE id=?", (rid,)).fetchone()
            return dict(row) if row else None

    def update_alert_rule(self, rid: int, **fields) -> bool:
        allowed = ["name", "metric", "operator", "threshold", "scope", "enabled", "notify_email",
                   "webhook_url", "webhook_type"]
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not sets:
            return False
        if "enabled" in sets:
            sets["enabled"] = int(sets["enabled"])
        cols = ", ".join(f"{k}=?" for k in sets)
        vals = [sets[k] for k in sets] + [rid]
        with self._conn_cm() as conn:
            conn.execute(f"UPDATE alert_rules SET {cols} WHERE id=?", vals)
            conn.commit()
            return True

    def delete_alert_rule(self, rid: int) -> bool:
        with self._conn_cm() as conn:
            conn.execute("DELETE FROM alert_rules WHERE id=?", (rid,))
            conn.commit()
            return True

    # ---------- 告警事件 ----------
    def insert_alert_event(self, rule_id, camera_id, message, severity, value, result_id=None) -> int:
        with self._conn_cm() as conn:
            cur = conn.execute(
                "INSERT INTO alert_events (rule_id,camera_id,message,severity,value,timestamp,acknowledged,notified,result_id) VALUES (?,?,?,?,?,?,0,0,?)",
                (rule_id, camera_id, message, severity, value, utc_iso(), result_id),
            )
            conn.commit()
            return cur.lastrowid

    def get_alert_event(self, alert_id: int) -> dict | None:
        with self._conn_cm() as conn:
            row = conn.execute("SELECT * FROM alert_events WHERE id=?", (alert_id,)).fetchone()
            return dict(row) if row else None

    def get_result_by_id(self, rid: int) -> dict | None:
        """单条检测记录（告警联动查看现场图用）。"""
        with self._conn_cm() as conn:
            row = conn.execute("SELECT * FROM detection_results WHERE id=?", (rid,)).fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["defects"] = json.loads(d["defects"]) if d["defects"] else []
            except Exception:
                d["defects"] = []
            return d

    def set_alert_verdict(self, alert_id: int, verdict: str, remark: str, judged_by: str) -> bool:
        """人工判定告警事件（第二期 G2）：confirmed / false_positive / missed。"""
        with self._conn_cm() as conn:
            cur = conn.execute(
                "UPDATE alert_events SET verdict=?, remark=?, judged_by=?, judged_at=?, acknowledged=1 WHERE id=?",
                (verdict, remark, judged_by, utc_iso(), alert_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def alert_statistics(self, days: int = 30) -> dict:
        """告警判定统计（第二期 G2）：误报率/确认率/待判定数，时间窗口按 UTC ISO 字符串比较。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat() if days and days > 0 else None
        where = " WHERE timestamp>=?" if cutoff else ""
        params = (cutoff,) if cutoff else ()
        with self._conn_cm() as conn:
            rows = conn.execute(
                f"SELECT COALESCE(verdict,'pending') AS v, COUNT(*) AS c FROM alert_events{where} GROUP BY v",
                params,
            ).fetchall()
        dist = {r["v"]: r["c"] for r in rows}
        total = sum(dist.values())
        judged = total - dist.get("pending", 0)
        fp = dist.get("false_positive", 0)
        confirmed = dist.get("confirmed", 0)
        return {
            "days": days,
            "total": total,
            "judged": judged,
            "pending": dist.get("pending", 0),
            "confirmed": confirmed,
            "false_positive": fp,
            "missed": dist.get("missed", 0),
            "false_positive_rate": round(fp / judged, 4) if judged else None,
            "confirmed_rate": round(confirmed / judged, 4) if judged else None,
        }

    def list_alerts(self, page=1, page_size=20, acknowledged=None) -> Tuple[List[dict], int]:
        clauses, params = [], []
        if acknowledged is not None:
            clauses.append("acknowledged=?")
            params.append(int(acknowledged))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn_cm() as conn:
            rows = conn.execute(
                f"SELECT * FROM alert_events{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [page_size, (page - 1) * page_size],
            ).fetchall()
            total = conn.execute(f"SELECT COUNT(*) FROM alert_events{where}", params).fetchone()[0]
            return [dict(r) for r in rows], total

    def acknowledge_alert(self, alert_id: int) -> bool:
        with self._conn_cm() as conn:
            conn.execute("UPDATE alert_events SET acknowledged=1 WHERE id=?", (alert_id,))
            conn.commit()
            return True

    def mark_alert_notified(self, alert_id: int) -> None:
        with self._conn_cm() as conn:
            conn.execute("UPDATE alert_events SET notified=1 WHERE id=?", (alert_id,))
            conn.commit()

    # ---------- 批次管理（第二期 G4） ----------
    def create_batch(self, batch_no: str, product: str = "", note: str = "") -> int:
        with self._conn_cm() as conn:
            cur = conn.execute(
                "INSERT INTO batches (batch_no, product, started_at, ended_at, note) VALUES (?,?,?,?,?)",
                (batch_no, product, utc_iso(), None, note),
            )
            conn.commit()
            return cur.lastrowid

    def get_batch(self, batch_id: str) -> dict | None:
        """按 batch_no 查询（detection_results.batch_id 存的是 batch_no）。"""
        with self._conn_cm() as conn:
            row = conn.execute("SELECT * FROM batches WHERE batch_no=?", (batch_id,)).fetchone()
            return dict(row) if row else None

    def list_batches(self) -> List[dict]:
        with self._conn_cm() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM batches ORDER BY id DESC").fetchall()]

    def end_batch(self, batch_id: str) -> bool:
        with self._conn_cm() as conn:
            cur = conn.execute(
                "UPDATE batches SET ended_at=? WHERE batch_no=?", (utc_iso(), batch_id)
            )
            conn.commit()
            return cur.rowcount > 0

    def report_by_batch(self, batch_id: str) -> dict:
        """按批次聚合报表（第二期 G4）：直接读 detection_results（batch_id 索引），
        保证与"按时间过滤"口径一致；返回总数/缺陷率/耗时/品类占比。
        """
        with self._conn_cm() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(defect_count),0) AS dc, "
                "COALESCE(SUM(total_count),0) AS tc, COALESCE(AVG(processing_time_ms),0) AS pt, "
                "COALESCE(SUM(CASE WHEN defect_count>0 THEN 1 ELSE 0 END),0) AS df "
                "FROM detection_results WHERE batch_id=?",
                (batch_id,),
            ).fetchone()
            total = row["total"] or 0
            df = row["df"] or 0
            shares = conn.execute(
                "SELECT json_extract(je.value,'$.class_name') AS class_name, COUNT(*) AS cnt "
                "FROM detection_results, json_each(detection_results.defects) AS je "
                "WHERE detection_results.batch_id=? "
                "AND json_extract(je.value,'$.class_name') IS NOT NULL GROUP BY class_name",
                (batch_id,),
            ).fetchall()
        return {
            "batch_id": batch_id,
            "total": total,
            "defect_count": row["dc"] or 0,
            "total_count": row["tc"] or 0,
            "defect_rate": round(df / total, 4) if total else 0.0,
            "defect_frame_rate": round(df / total, 4) if total else 0.0,
            "avg_processing_ms": round(row["pt"] or 0, 2),
            "by_type": [{"class_name": s["class_name"], "count": s["cnt"]} for s in shares],
        }

    def export_sample_rows(self, verdicts: List[str], limit: int) -> List[dict]:
        """训练样本导出（第二期 1.3）：取已判定（confirmed/false_positive）告警关联的缺陷帧。

        同一帧可能被多条规则触发多个 alert_event，故按 detection_results.id 去重；
        仅返回落盘且有 image_path 的结果。返回 [{image_path, defects(json str)}, ...]。
        """
        if not verdicts or limit <= 0:
            return []
        placeholders = ",".join("?" for _ in verdicts)
        sql = (
            f"SELECT DISTINCT dr.id AS rid, dr.image_path AS image_path, dr.defects AS defects "
            f"FROM alert_events ae JOIN detection_results dr ON dr.id = ae.result_id "
            f"WHERE ae.verdict IN ({placeholders}) "
            f"AND dr.image_path IS NOT NULL AND dr.image_path != '' "
            f"ORDER BY dr.id LIMIT ?"
        )
        with self._conn_cm() as conn:
            cur = conn.execute(sql, list(verdicts) + [int(limit)])
            return [
                {"image_path": r["image_path"], "defects": r["defects"]}
                for r in cur.fetchall()
            ]

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

    # ---------- 模型版本 ----------
    def list_model_versions(self) -> List[dict]:
        with self._conn_cm() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM model_versions ORDER BY id DESC").fetchall()]

    def get_model_version(self, mv_id: int) -> dict | None:
        with self._conn_cm() as conn:
            row = conn.execute("SELECT * FROM model_versions WHERE id=?", (mv_id,)).fetchone()
            return dict(row) if row else None

    def create_model_version(self, mv: dict) -> int:
        with self._conn_cm() as conn:
            cur = conn.execute(
                "INSERT INTO model_versions (name,version,file_path,metric,active,description,created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    mv["name"], mv.get("version", "1.0.0"), mv.get("file_path", ""),
                    mv.get("metric", 0.0), int(mv.get("active", False)), mv.get("description", ""),
                    mv.get("created_at", utc_iso()),
                ),
            )
            conn.commit()
            return cur.lastrowid

    def set_active_model_version(self, mv_id: int) -> None:
        with self._conn_cm() as conn:
            conn.execute("UPDATE model_versions SET active=0")
            conn.execute("UPDATE model_versions SET active=1 WHERE id=?", (mv_id,))
            conn.commit()

    def get_active_model_version(self) -> dict | None:
        with self._conn_cm() as conn:
            row = conn.execute("SELECT * FROM model_versions WHERE active=1 LIMIT 1").fetchone()
            return dict(row) if row else None

    def delete_model_version(self, mv_id: int) -> bool:
        with self._conn_cm() as conn:
            conn.execute("DELETE FROM model_versions WHERE id=?", (mv_id,))
            conn.commit()
            return True
