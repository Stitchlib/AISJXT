from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import get_current_user, require_operator
from ..models import AckResult, AlertEvent, AlertEventPage, AlertOperator, AlertMetric, AlertRule, User
from .. import notifier

router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[Depends(get_current_user)])

# 告警人工判定（第二期 G2）
VALID_VERDICTS = ("confirmed", "false_positive", "missed")


class AlertVerdictRequest(BaseModel):
    verdict: str = Field(..., description="confirmed / false_positive / missed")
    remark: Optional[str] = None


class AlertStatistics(BaseModel):
    days: int
    total: int
    judged: int
    pending: int
    confirmed: int
    false_positive: int
    missed: int
    false_positive_rate: Optional[float] = None
    confirmed_rate: Optional[float] = None


class AlertRuleCreate(BaseModel):
    name: str
    metric: AlertMetric = AlertMetric.DEFECT_RATE
    operator: AlertOperator = AlertOperator.GT
    threshold: float = 0.5
    scope: str = "all"
    enabled: bool = True
    notify_email: Optional[str] = None
    # 多渠道通知（第二期 G3）
    webhook_url: Optional[str] = None
    webhook_type: Optional[str] = None  # generic / dingtalk / feishu / wecom
    # 告警冷却与聚合（第三期 2.1）：0=不冷却（旧行为）；silence_until=UTC ISO 时刻，之前静默
    cooldown_seconds: int = Field(default=0, ge=0, le=7 * 86400)
    silence_until: Optional[str] = None


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    metric: Optional[AlertMetric] = None
    operator: Optional[AlertOperator] = None
    threshold: Optional[float] = None
    scope: Optional[str] = None
    enabled: Optional[bool] = None
    notify_email: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_type: Optional[str] = None
    cooldown_seconds: Optional[int] = Field(default=None, ge=0, le=7 * 86400)
    silence_until: Optional[str] = None  # 显式传 null 表示清除静默窗口


class AlertTestResult(BaseModel):
    ok: bool
    message: str
    webhook_type: Optional[str] = None


@router.get("/rules", response_model=list[AlertRule])
def list_rules(request: Request):
    return request.app.state.db.list_alert_rules()


@router.post("/rules", status_code=201, response_model=AlertRule)
def create_rule(body: AlertRuleCreate, request: Request):
    rid = request.app.state.db.create_alert_rule(body.model_dump())
    return request.app.state.db.get_alert_rule(rid)


@router.put("/rules/{rule_id}", response_model=AlertRule)
def update_rule(rule_id: int, body: AlertRuleUpdate, request: Request):
    if not request.app.state.db.update_alert_rule(rule_id, **body.model_dump(exclude_unset=True)):
        raise HTTPException(status_code=404, detail="规则不存在")
    return request.app.state.db.get_alert_rule(rule_id)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, request: Request):
    if not request.app.state.db.delete_alert_rule(rule_id):
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"ok": True, "removed": rule_id}


@router.post("/rules/{rule_id}/test", response_model=AlertTestResult)
def test_rule_webhook(rule_id: int, request: Request, _op: User = Depends(require_operator)):
    """测试发送：按规则配置的 webhook 渠道发一次连通性测试（第二期 G3）。"""
    rule = request.app.state.db.get_alert_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    url = rule.get("webhook_url")
    if not url:
        raise HTTPException(status_code=400, detail="该规则未配置 webhook_url")
    wt = rule.get("webhook_type") or "generic"
    if wt not in notifier.VALID_WEBHOOK_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的 webhook_type: {wt}")
    ok, msg = notifier.test_webhook(url, wt)
    return AlertTestResult(ok=ok, message=msg or ("发送成功" if ok else "发送失败"), webhook_type=wt)


@router.get("/events", response_model=AlertEventPage)
def list_events(request: Request, page: int = 1, page_size: int = 20, acknowledged: Optional[bool] = None):
    page = max(1, page)
    page_size = min(max(1, page_size), 1000)
    rows, total = request.app.state.db.list_alerts(page, page_size, acknowledged)
    return {"page": page, "page_size": page_size, "total": total, "items": rows}


@router.post("/events/{event_id}/acknowledge", response_model=AckResult)
def acknowledge(event_id: int, request: Request):
    if not request.app.state.db.acknowledge_alert(event_id):
        raise HTTPException(status_code=404, detail="事件不存在")
    return {"ok": True, "acknowledged": event_id}


@router.get("/statistics", response_model=AlertStatistics)
def statistics(request: Request, days: int = 30):
    """告警判定统计（第二期 G2）：误报率/确认率/待判定数。"""
    days = max(0, min(days, 3650))
    return request.app.state.db.alert_statistics(days)


@router.put("/events/{event_id}/verdict", response_model=AlertEvent)
def set_verdict(
    event_id: int,
    body: AlertVerdictRequest,
    request: Request,
    user: User = Depends(require_operator),  # viewer 不可判定
):
    """人工判定告警事件：确认缺陷 / 误报 / 漏报（第二期 G2）。判定即视为已确认。"""
    if body.verdict not in VALID_VERDICTS:
        raise HTTPException(status_code=400, detail=f"verdict 必须为 {'/'.join(VALID_VERDICTS)}")
    db = request.app.state.db
    if not db.get_alert_event(event_id):
        raise HTTPException(status_code=404, detail="事件不存在")
    db.set_alert_verdict(event_id, body.verdict, body.remark or "", user.username)
    # 审计（L3 延续）：判定行为留痕，便于追溯谁把告警标为误报
    try:
        request.app.state.audit.record(
            actor=user.username, action="alert.verdict", target=str(event_id),
            detail=f"verdict={body.verdict} remark={body.remark or ''}",
            ip=request.client.host if request.client else "",
        )
    except Exception:
        pass
    return db.get_alert_event(event_id)
