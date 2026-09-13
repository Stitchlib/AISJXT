"""批次/工单域：批次生命周期与批次维度聚合报表（第二期 G4）。"""
from __future__ import annotations

from typing import List

from ..models import utc_iso


class BatchesMixin:
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
