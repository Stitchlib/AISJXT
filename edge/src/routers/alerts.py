from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import get_current_user
from ..models import AlertOperator, AlertMetric, User

router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[Depends(get_current_user)])


class AlertRuleCreate(BaseModel):
    name: str
    metric: AlertMetric = AlertMetric.DEFECT_RATE
    operator: AlertOperator = AlertOperator.GT
    threshold: float = 0.5
    scope: str = "all"
    enabled: bool = True
    notify_email: Optional[str] = None


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    metric: Optional[AlertMetric] = None
    operator: Optional[AlertOperator] = None
    threshold: Optional[float] = None
    scope: Optional[str] = None
    enabled: Optional[bool] = None
    notify_email: Optional[str] = None


@router.get("/rules")
def list_rules(request: Request):
    return request.app.state.db.list_alert_rules()


@router.post("/rules", status_code=201)
def create_rule(body: AlertRuleCreate, request: Request):
    rid = request.app.state.db.create_alert_rule(body.model_dump())
    return request.app.state.db.get_alert_rule(rid)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, body: AlertRuleUpdate, request: Request):
    if not request.app.state.db.update_alert_rule(rule_id, **body.model_dump(exclude_unset=True)):
        raise HTTPException(status_code=404, detail="规则不存在")
    return request.app.state.db.get_alert_rule(rule_id)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, request: Request):
    if not request.app.state.db.delete_alert_rule(rule_id):
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"ok": True, "removed": rule_id}


@router.get("/events")
def list_events(request: Request, page: int = 1, page_size: int = 20, acknowledged: Optional[bool] = None):
    page = max(1, page)
    page_size = min(max(1, page_size), 1000)
    rows, total = request.app.state.db.list_alerts(page, page_size, acknowledged)
    return {"page": page, "page_size": page_size, "total": total, "items": rows}


@router.post("/events/{event_id}/acknowledge")
def acknowledge(event_id: int, request: Request):
    if not request.app.state.db.acknowledge_alert(event_id):
        raise HTTPException(status_code=404, detail="事件不存在")
    return {"ok": True, "acknowledged": event_id}
