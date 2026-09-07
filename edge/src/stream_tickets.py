"""一次性短时效票据（M7，第二期扩展为 video/media 共用）。

用途：`<img>` 标签无法附带 Authorization 头，视频流与缺陷图片访问以 ?ticket= 换取临时授权。
票据存于 app.state（单实例内存），一次性消费、60 秒有效，避免 JWT 落入访问日志。
"""
from __future__ import annotations

import secrets
import time

from fastapi import HTTPException, Request

TICKET_TTL_SECONDS = 60


def _store(request: Request) -> dict:
    store = getattr(request.app.state, "stream_tickets", None)
    if store is None:
        store = {}
        request.app.state.stream_tickets = store
    return store


def issue(request: Request) -> tuple[str, int]:
    """签发一次性票据，返回 (ticket, ttl)。"""
    ticket = secrets.token_urlsafe(24)
    _store(request)[ticket] = time.time() + TICKET_TTL_SECONDS
    return ticket, TICKET_TTL_SECONDS


def consume(request: Request, ticket: str) -> bool:
    """校验并消费一次性票据；过期或不存在返回 False。"""
    if not ticket:
        return False
    store = _store(request)
    exp = store.get(ticket)
    if exp is None:
        return False
    store.pop(ticket, None)  # 一次性：消费即作废
    if exp < time.time():
        return False
    return True


def authenticate(request: Request, auth_service) -> bool:
    """票据或 Bearer 任一通过即放行；均无效抛 401。

    供视频流 / 媒体等需要 `<img>` 直连的场景使用（标准 API 请直接用 get_current_user 依赖）。
    """
    ticket = request.query_params.get("ticket")
    if ticket and consume(request, ticket):
        return True
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        user = auth_service.get_user_from_token(header[len("Bearer "):])
        if user is not None:
            return True
    raise HTTPException(status_code=401, detail="未授权：需要有效的临时票据或令牌")
