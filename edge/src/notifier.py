"""告警与通知：规则评估 + 应用内事件 + 可选邮件。

职责边界：
- process_alerts：由 inspection_engine 在每次检测后调用，命中规则则落库 alert_events 并(可选)发邮件。
- send_email：SMTP 可选，未启用或失败时安全降级（仅记录日志，不影响主流程）。
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import List, Optional

from .config_manager import ConfigManager
from .database import Database
from .models import DetectionResult

logger = logging.getLogger("notifier")


def _compare(value: float, op: str, threshold: float) -> bool:
    if op == "gt":
        return value > threshold
    if op == "ge":
        return value >= threshold
    if op == "lt":
        return value < threshold
    if op == "le":
        return value <= threshold
    return False


def _metric_value(result: DetectionResult, metric: str) -> Optional[float]:
    if metric == "defect_rate":
        return result.defect_rate
    if metric == "defect_count":
        return float(result.defect_count)
    if metric == "processing_time_ms":
        return result.processing_time_ms
    return None


def send_email(cm: ConfigManager, to: str, subject: str, body: str) -> bool:
    """发送告警邮件；SMTP 未启用或异常时返回 False 并降级。

    支持三种连接模式（由 config.smtp_mode 控制）：
    - ssl:       SMTP over SSL（默认，端口通常 465）
    - starttls:  明文连接后升级 TLS（端口通常 587）
    - plain:     明文连接，不加密（仅用于内网/本地调试，如本仓库测试）
    """
    cfg = cm.get()
    if not cfg.smtp_enabled:
        logger.info("SMTP 未启用，跳过邮件: %s", subject)
        return False
    mode = (cfg.smtp_mode or "ssl").lower()
    try:
        msg = EmailMessage()
        msg["From"] = cfg.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        if mode == "ssl":
            server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=10)
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10)
        with server:
            if mode == "starttls":
                server.starttls()
            if cfg.smtp_user:
                server.login(cfg.smtp_user, cfg.smtp_pass)
            server.send_message(msg)
        logger.info("告警邮件已发送至 %s (mode=%s)", to, mode)
        return True
    except Exception as e:  # pragma: no cover - 依赖外部 SMTP
        logger.warning("邮件发送失败: %s", e)
        return False


def process_alerts(result: DetectionResult, db: Database, cm: ConfigManager) -> List[int]:
    """评估启用中的告警规则，命中即记录事件（可选邮件）。返回新建事件 id 列表。"""
    created: List[int] = []
    rules = db.list_alert_rules()
    for r in rules:
        if not r.get("enabled"):
            continue
        if r["scope"] != "all" and r["scope"] != result.camera_id:
            continue
        value = _metric_value(result, r["metric"])
        if value is None:
            continue
        if not _compare(value, r["operator"], r["threshold"]):
            continue
        severity = "critical" if value >= r["threshold"] * 1.5 else "warning"
        msg = (
            f"规则[{r['name']}] 摄像头[{result.camera_id}] "
            f"{r['metric']}={value:.3f} 触发阈值 {r['threshold']}"
        )
        aid = db.insert_alert_event(r["id"], result.camera_id, msg, severity, value)
        created.append(aid)
        if r.get("notify_email"):
            body = (
                f"AI 视觉质检告警\n\n{msg}\n"
                f"时间: {result.timestamp}\n仿真数据: {result.is_simulation}\n"
                f"缺陷数: {result.defect_count}/{result.total_count}"
            )
            if send_email(cm, r["notify_email"], "AI视觉质检告警", body):
                db.mark_alert_notified(aid)
    return created
