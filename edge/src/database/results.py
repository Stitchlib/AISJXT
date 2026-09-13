"""检测结果域：写入、分页/条件查询、增量聚合统计、CSV 导出、保留期清理。

批量写入提供 executemany 单事务路径，满足高吞吐与离线导入场景；
聚合计数器增量维护，统计查询 O(1) 读取，避免百万行全表扫描。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import List, Tuple


class ResultsMixin:
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
