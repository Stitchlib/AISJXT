"""告警域：规则 CRUD、冷却/聚合事件、人工判定、告警统计与训练样本导出。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from ..models import utc_iso


class AlertsMixin:
    # ---------- 告警规则 ----------
    def create_alert_rule(self, rule: dict) -> int:
        with self._conn_cm() as conn:
            cur = conn.execute(
                "INSERT INTO alert_rules (name,metric,operator,threshold,scope,enabled,notify_email,webhook_url,webhook_type,cooldown_seconds,silence_until,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rule["name"], rule["metric"], rule["operator"], rule["threshold"],
                    rule["scope"], int(rule.get("enabled", True)), rule.get("notify_email"),
                    rule.get("webhook_url"), rule.get("webhook_type"),
                    max(0, int(rule.get("cooldown_seconds") or 0)),
                    rule.get("silence_until"),
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
                   "webhook_url", "webhook_type", "cooldown_seconds", "silence_until"]
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        # 显式传入 cooldown_seconds=0 是有效语义（关闭冷却），不能被 None 过滤吞掉
        if fields.get("cooldown_seconds") == 0:
            sets["cooldown_seconds"] = 0
        # 显式传入 silence_until=None 表示清除静默窗口
        if "silence_until" in fields and fields["silence_until"] is None:
            sets["silence_until"] = None
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

    # ---------- 告警冷却与聚合（第三期 2.1） ----------
    def get_latest_alert_event(self, rule_id: int, camera_id: str) -> dict | None:
        """该规则+摄像头最近一次事件（冷却窗口判定与聚合目标）。"""
        with self._conn_cm() as conn:
            row = conn.execute(
                "SELECT * FROM alert_events WHERE rule_id=? AND camera_id=? "
                "ORDER BY id DESC LIMIT 1",
                (rule_id, camera_id),
            ).fetchone()
            return dict(row) if row else None

    def bump_alert_event_repeat(self, alert_id: int, value: float) -> int:
        """冷却窗口内重复命中：聚合到既有事件（repeat_count+1，刷新观测值），不新建不通知。"""
        with self._conn_cm() as conn:
            cur = conn.execute(
                "UPDATE alert_events SET repeat_count=repeat_count+1, value=? WHERE id=?",
                (value, alert_id),
            )
            conn.commit()
            return cur.rowcount

    def recover_alert_events(self, rule_id: int, camera_id: str) -> int:
        """状态恢复：关闭该规则+摄像头的全部未恢复事件（recovered=1）。

        返回关闭数（0=本来就没有活动事件）。供"恢复通知"判断：仅当本帧未命中
        且确有活动事件时才发一次恢复通知，避免逐帧空转 UPDATE 扫大表。
        """
        with self._conn_cm() as conn:
            cur = conn.execute(
                "UPDATE alert_events SET recovered=1, recovered_at=? "
                "WHERE rule_id=? AND camera_id=? AND recovered=0",
                (utc_iso(), rule_id, camera_id),
            )
            conn.commit()
            return cur.rowcount

    def close_active_alert_events(self, rule_id: int, camera_id: str) -> int:
        """新事件接续：同一规则+摄像头产生新事件时关闭旧活动事件（不视为恢复）。

        与 recover_alert_events 的区别：本方法用于"持续告警被新事件接续"的场景，
        旧事件关闭但不发恢复通知（条件并未恢复，只是换了一个新事件承载）。
        """
        with self._conn_cm() as conn:
            cur = conn.execute(
                "UPDATE alert_events SET recovered=1 "
                "WHERE rule_id=? AND camera_id=? AND recovered=0",
                (rule_id, camera_id),
            )
            conn.commit()
            return cur.rowcount

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
