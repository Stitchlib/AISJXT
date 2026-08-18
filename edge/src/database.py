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
from datetime import datetime
from pathlib import Path
from typing import List, Tuple


class Database:
    def __init__(self, db_path: str = "data/inspection.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
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
                    is_simulation INTEGER
                )
                """
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
                    value REAL, timestamp TEXT, acknowledged INTEGER, notified INTEGER
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
            conn.commit()

    # ---------- 检测结果写入 ----------
    def insert_result(self, row: dict) -> int:
        with self._conn_cm() as conn:
            cur = conn.execute(
                """
                INSERT INTO detection_results
                (timestamp, camera_id, image_path, defects, total_count,
                 defect_count, defect_rate, processing_time_ms, is_simulation)
                VALUES (?,?,?,?,?,?,?,?,?)
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
                ),
            )
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
            )
            for r in rows
        ]
        with self._conn_cm() as conn:
            conn.executemany(
                """
                INSERT INTO detection_results
                (timestamp, camera_id, image_path, defects, total_count,
                 defect_count, defect_rate, processing_time_ms, is_simulation)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                payload,
            )
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
    ) -> Tuple[List[dict], int]:
        clauses = []
        params: list = []
        if camera_id:
            clauses.append("camera_id=?")
            params.append(camera_id)
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

    def get_statistics(self) -> dict:
        with self._conn_cm() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) total,
                       COALESCE(SUM(defect_count),0) defects,
                       COALESCE(SUM(total_count),0) total_count,
                       COALESCE(AVG(processing_time_ms),0) avg_ms,
                       COALESCE(SUM(CASE WHEN is_simulation THEN 1 ELSE 0 END),0) sim_count
                FROM detection_results
                """
            ).fetchone()
            total_count = row[2] or 0
            return {
                "total": row[0],
                "defect_count": row[1],
                "total_count": total_count,
                "defect_rate": round(row[1] / total_count, 4) if total_count else 0.0,
                "avg_processing_ms": round(row[3], 2),
                "simulated_records": row[4],
            }

    def get_type_shares(self) -> List[dict]:
        rows, _ = self.query_results(1, 10_000_000)
        counter: dict[str, int] = {}
        for r in rows:
            for d in r.get("defects", []) or []:
                cls = d.get("class_name", "未知")
                counter[cls] = counter.get(cls, 0) + 1
        return [{"class_name": k, "count": v} for k, v in sorted(counter.items(), key=lambda x: -x[1])]

    def get_trend(self, bucket: str = "day") -> List[dict]:
        from collections import defaultdict

        agg = defaultdict(lambda: [0, 0])
        with self._conn_cm() as conn:
            for r in conn.execute(
                "SELECT timestamp, total_count, defect_count FROM detection_results"
            ).fetchall():
                ts = r["timestamp"]
                key = ts[:13] if bucket == "hour" else ts[:10]
                agg[key][0] += r["total_count"]
                agg[key][1] += r["defect_count"]
        out = []
        for k in sorted(agg):
            total, dc = agg[k]
            out.append(
                {"bucket": k, "total": total, "defect_count": dc,
                 "defect_rate": round(dc / total, 4) if total else 0.0}
            )
        return out

    def export_csv(self, path: str) -> str:
        rows, _ = self.query_results(page=1, page_size=10_000_000)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "id", "timestamp", "camera_id", "defect_count", "total_count",
                    "defect_rate", "processing_time_ms", "is_simulation", "defects",
                ]
            )
            for r in rows:
                defects = r.get("defects")
                w.writerow(
                    [
                        r["id"], r["timestamp"], r["camera_id"], r["defect_count"],
                        r["total_count"], r["defect_rate"], r["processing_time_ms"],
                        r["is_simulation"], json.dumps(defects, ensure_ascii=False),
                    ]
                )
        return path

    # ---------- 用户 ----------
    def get_user_by_username(self, username: str) -> dict | None:
        with self._conn_cm() as conn:
            row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            return dict(row) if row else None

    def create_user(self, username, display_name, role, salt_hex, hash_hex, disabled=False) -> int:
        with self._conn_cm() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, display_name, role, disabled, created_at, salt, password_hash) VALUES (?,?,?,?,?,?,?)",
                (username, display_name, role, int(disabled), datetime.now().isoformat(), salt_hex, hash_hex),
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
                "INSERT INTO alert_rules (name,metric,operator,threshold,scope,enabled,notify_email,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    rule["name"], rule["metric"], rule["operator"], rule["threshold"],
                    rule["scope"], int(rule.get("enabled", True)), rule.get("notify_email"),
                    rule.get("created_at", datetime.now().isoformat()),
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
        allowed = ["name", "metric", "operator", "threshold", "scope", "enabled", "notify_email"]
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
    def insert_alert_event(self, rule_id, camera_id, message, severity, value) -> int:
        with self._conn_cm() as conn:
            cur = conn.execute(
                "INSERT INTO alert_events (rule_id,camera_id,message,severity,value,timestamp,acknowledged,notified) VALUES (?,?,?,?,?,?,0,0)",
                (rule_id, camera_id, message, severity, value, datetime.now().isoformat()),
            )
            conn.commit()
            return cur.lastrowid

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
                    mv.get("created_at", datetime.now().isoformat()),
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
