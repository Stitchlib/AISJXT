"""告警与通知：规则评估 + 冷却聚合 + 应用内事件 + 邮件 + 多渠道 webhook。

职责边界：
- process_alerts：由 inspection_engine 在每次检测后调用。评估启用中的规则：
  命中即落库 alert_events 并(可选)发邮件/webhook；支持冷却窗口（窗口内仅聚合
  repeat_count，不新建事件不发送）、运营静默（silence_until 前完全跳过）、
  状态恢复通知（条件回落到阈值内时发一次"已恢复"）。
- send_email：SMTP 可选，未启用或失败时安全降级（仅记录日志，不影响主流程）。
- send_webhook：HTTP POST 到钉钉/飞书/企微/通用机器人（均为标准 HTTP，无需 SDK）。
  - 慢 webhook（如企业机器人）通过 asyncio.to_thread 在引擎侧异步调用，不影响检测循环节拍；
  - 发送失败重试 1 次后仅记日志与标记 notified 状态，绝不"轰炸"或阻塞主流程。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import List, Optional, Tuple

from .config_manager import ConfigManager
from .database import Database
from .models import DetectionResult

logger = logging.getLogger("notifier")

# 支持的 webhook 类型白名单（第二期 G3）
VALID_WEBHOOK_TYPES = ("generic", "dingtalk", "feishu", "wecom")


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


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    """解析 ISO 时间戳（utc_iso 写入，含/不含时区均可）；失败返回 None。"""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _build_webhook_payload(webhook_type: str, text: str) -> dict:
    """按机器人类型封装消息体（均为各平台约定的 JSON 结构）。"""
    wt = (webhook_type or "generic").lower()
    if wt == "dingtalk":
        return {"msgtype": "text", "text": {"content": text}}
    if wt == "feishu":
        return {"msg_type": "text", "content": {"text": text}}
    if wt == "wecom":
        return {"msgtype": "text", "text": {"content": text}}
    # generic：透传 {text: ...}（可选 HMAC 签名头由调用方加）
    return {"text": text}


def _post_json(url: str, payload: dict, secret: Optional[str] = None, timeout: int = 10) -> int:
    """同步 POST JSON；失败时抛异常由调用方处理重试。返回 HTTP 状态码。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "AIQC-Notifier/1.0"}
    if secret:
        # 通用类型可选 HMAC-SHA256 签名头，便于服务端校验来源
        sig = hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()
        headers["X-Signature"] = f"sha256={sig}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.getcode() or 200


def send_webhook(
    url: str,
    webhook_type: str,
    text: str,
    secret: Optional[str] = None,
    timeout: int = 10,
    retries: int = 1,
) -> Tuple[bool, Optional[str]]:
    """发送 webhook 通知；失败重试最多 retries 次（默认 1 次）。

    返回 (ok, error_message)。任何异常都被捕获并降级，绝不让调用方崩溃。
    """
    wt = (webhook_type or "generic").lower()
    if wt not in VALID_WEBHOOK_TYPES:
        return False, f"不支持的 webhook_type: {webhook_type}"
    payload = _build_webhook_payload(wt, text)
    last_err: Optional[str] = None
    for attempt in range(retries + 1):
        try:
            status = _post_json(url, payload, secret, timeout)
            if 200 <= status < 300:
                return True, None
            last_err = f"HTTP {status}"
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.reason}"
        except Exception as e:  # 网络/超时/URL 错误等
            last_err = str(e)
        if attempt < retries:
            logger.warning("webhook 发送失败（第 %d 次，将重试）: %s", attempt + 1, last_err)
    logger.warning("webhook 发送最终失败（已重试 %d 次）: %s", retries, last_err)
    return False, last_err


def test_webhook(url: str, webhook_type: str, timeout: int = 10) -> Tuple[bool, Optional[str]]:
    """测试发送：用固定测试文案发一次，返回 (ok, message)。"""
    ok, err = send_webhook(
        url, webhook_type, "【AI视觉质检】webhook 连通性测试，收到说明配置正常。", timeout=timeout
    )
    if ok:
        return True, "发送成功"
    return False, err or "发送失败"


def send_email(cm: ConfigManager, to: str, subject: str, body: str) -> bool:
    """发送告警邮件；SMTP 未启用或异常时返回 False 并降级。

    支持三种连接模式（由 config.smtp_mode 控制）：
    - ssl:       SMTP over SSL（默认，端口通常 465）
    - starttls:  明文连接后升级 TLS（端口通常 587）
    - plain:     明文连接，不加密（仅用于内网/本地调试，如本仓库测试）
    """
    import smtplib

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


def _dispatch_notifications(
    rule: dict, alert_id: int, msg: str, result: DetectionResult,
    db: Database, cm: ConfigManager, bus=None,
) -> bool:
    """按规则渠道发送一次告警通知（邮件 + webhook）。返回是否至少一个渠道成功。

    bus 不为空时走异步投递（第三期 2.2，由 notification_worker 消费）；
    为空时同步发送（兼容单测与现有行为）。
    """
    if bus is not None:
        return bus.submit_alert(rule, alert_id, msg, result)
    notified = False
    if rule.get("notify_email"):
        body = (
            f"AI 视觉质检告警\n\n{msg}\n"
            f"时间: {result.timestamp}\n仿真数据: {result.is_simulation}\n"
            f"缺陷数: {result.defect_count}/{result.total_count}"
        )
        if send_email(cm, rule["notify_email"], "AI视觉质检告警", body):
            notified = True
    wh_url = rule.get("webhook_url")
    if wh_url:
        wh_type = rule.get("webhook_type") or "generic"
        ok, _err = send_webhook(wh_url, wh_type, f"AI视觉质检告警\n{msg}")
        if ok:
            notified = True
        else:
            logger.warning("告警[%s] webhook 通知失败: %s", alert_id, _err)
    return notified


def _notify_recovery(
    rule: dict, result: DetectionResult, db: Database, cm: ConfigManager, bus=None,
) -> None:
    """状态恢复通知：指标回落到阈值内时发一次"已恢复"（走同一组渠道，失败仅记日志）。"""
    msg = (
        f"规则[{rule['name']}] 摄像头[{result.camera_id}] "
        f"{rule['metric']} 已回落到阈值内（阈值 {rule['threshold']}），告警恢复"
    )
    logger.info("告警恢复: %s", msg)
    if bus is not None:
        bus.submit_recovery(rule, msg)
        return
    if rule.get("notify_email"):
        body = f"AI 视觉质检告警恢复\n\n{msg}\n时间: {result.timestamp}"
        send_email(cm, rule["notify_email"], "AI视觉质检告警恢复", body)
    wh_url = rule.get("webhook_url")
    if wh_url:
        wh_type = rule.get("webhook_type") or "generic"
        ok, _err = send_webhook(wh_url, wh_type, f"AI视觉质检告警恢复\n{msg}")
        if not ok:
            logger.warning("恢复通知 webhook 发送失败: %s", _err)


def process_alerts(result: DetectionResult, db: Database, cm: ConfigManager, bus=None) -> List[int]:
    """评估启用中的告警规则（第三期 2.1 冷却/聚合/静默/恢复），返回新建事件 id 列表。

    语义（按规则+摄像头维度独立判定）：
    - silence_until 在未来 → 完全跳过（不评估/不建事件/不通知/不聚合/不恢复）；
    - 本帧命中：
      - cooldown_seconds>0 且最近事件仍在冷却窗口内 → 聚合：repeat_count+1（不新建不发送）；
      - 否则新建事件并通知；若上一事件仍未恢复，标记为"持续告警"摘要（接续关闭旧事件）；
    - 本帧未命中：若存在活动事件 → 关闭并（有配置渠道时）发一次恢复通知。
    - cooldown_seconds=0：与旧版行为完全一致（每次命中都新建事件并通知）。
    """
    created: List[int] = []
    now = datetime.now(timezone.utc)
    rules = db.list_alert_rules()
    for r in rules:
        if not r.get("enabled"):
            continue
        if r["scope"] != "all" and r["scope"] != result.camera_id:
            continue
        # 运营静默窗口：silence_until 之前整条规则跳过（抑制风暴期间的误报噪声）
        silence_until = _parse_iso(r.get("silence_until"))
        if silence_until is not None and now < silence_until:
            continue
        value = _metric_value(result, r["metric"])
        if value is None:
            continue
        if not _compare(value, r["operator"], r["threshold"]):
            # 状态恢复：仅当确有活动事件时才关闭并发恢复通知（避免逐帧空转）
            if db.recover_alert_events(r["id"], result.camera_id):
                _notify_recovery(r, result, db, cm, bus)
            continue
        cooldown = int(r.get("cooldown_seconds") or 0)
        latest = db.get_latest_alert_event(r["id"], result.camera_id)
        if cooldown > 0 and latest is not None:
            last_ts = _parse_iso(latest.get("timestamp"))
            if last_ts is not None and (now - last_ts).total_seconds() < cooldown:
                # 冷却窗口内：聚合到既有事件，不新建、不发通知
                db.bump_alert_event_repeat(latest["id"], value)
                continue
        severity = "critical" if value >= r["threshold"] * 1.5 else "warning"
        msg = (
            f"规则[{r['name']}] 摄像头[{result.camera_id}] "
            f"{r['metric']}={value:.3f} 触发阈值 {r['threshold']}"
        )
        # 冷却结束仍持续（上一事件未恢复）→ 持续告警摘要（聚合前次重复计数）
        if latest is not None and not latest.get("recovered"):
            prev_repeats = int(latest.get("repeat_count") or 0)
            msg += f"（持续告警：前次事件已重复 {prev_repeats} 次，仍未恢复）"
            db.close_active_alert_events(r["id"], result.camera_id)
        aid = db.insert_alert_event(
            r["id"], result.camera_id, msg, severity, value, result_id=result.id
        )
        created.append(aid)
        if _dispatch_notifications(r, aid, msg, result, db, cm, bus):
            db.mark_alert_notified(aid)
    return created
