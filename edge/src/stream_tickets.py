"""一次性短时效票据（M7，第二期扩展为 video/media 共用，第三期 1.3 扩展到 WS 握手）。

用途：
- `<img>` 标签无法附带 Authorization 头，视频流与缺陷图片访问以 ?ticket= 换取临时授权；
- WebSocket 握手以 ?ticket= 替代 ?token=，避免 JWT 落入 access log（第三期 1.3/M3）。

票据存于 app.state（单实例内存），一次性消费、默认 60 秒有效（WS 票据 30 秒），
可绑定签发者用户名（WS 控制面需要角色信息）。
"""
from __future__ import annotations

import secrets
import time

from fastapi import HTTPException, Request

TICKET_TTL_SECONDS = 60
WS_TICKET_TTL_SECONDS = 30


def _store(request: Request) -> dict:
    store = getattr(request.app.state, "stream_tickets", None)
    if store is None:
        store = {}
        request.app.state.stream_tickets = store
    return store


def issue(request: Request, ttl: int = TICKET_TTL_SECONDS, username: str | None = None) -> tuple[str, int]:
    """签发一次性票据，返回 (ticket, ttl)。username 用于 WS 控制面解析身份。"""
    ticket = secrets.token_urlsafe(24)
    _store(request)[ticket] = {"exp": time.time() + ttl, "username": username}
    return ticket, ttl


def consume(request: Request, ticket: str) -> bool:
    """校验并消费一次性票据；过期或不存在返回 False。

    兼容历史 float 格式（仅 exp；重启后内存清空，实际不会再出现）。
    """
    if not ticket:
        return False
    store = _store(request)
    entry = store.get(ticket)
    if entry is None:
        return False
    store.pop(ticket, None)  # 一次性：消费即作废
    exp = entry["exp"] if isinstance(entry, dict) else entry
    if exp < time.time():
        return False
    return True


def consume_identity(request: Request, ticket: str) -> str | None:
    """一次性消费票据并返回签发时绑定的用户名；无效/过期/未绑定返回 None。

    供 WS 握手鉴权（第三期 1.3）：票据即临时身份，换取后按用户名回查用户与角色。
    """
    if not ticket:
        return None
    store = _store(request)
    entry = store.get(ticket)
    if entry is None:
        return None
    store.pop(ticket, None)
    if isinstance(entry, dict):
        if entry.get("exp", 0) < time.time():
            return None
        return entry.get("username")
    # 旧格式（float，无身份绑定）
    if entry < time.time():
        return None
    return None


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
