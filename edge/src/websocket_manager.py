"""WebSocket 连接管理：实时数据推送的出口。

inspection_engine 产生检测结果后调用 broadcast()；前端订阅后实时接收。
采用连接列表 + 异常隔离，单个客户端断开不影响其他客户端与检测循环。
"""
from __future__ import annotations

import asyncio
from typing import Dict, List

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.active: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, set] = {}

    async def connect(self, ws: WebSocket, camera_id: str | None = None) -> None:
        await ws.accept()
        self.active.append(ws)
        self.subscriptions[ws] = {camera_id} if camera_id else set()

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)
        self.subscriptions.pop(ws, None)

    async def send(self, ws: WebSocket, message: dict) -> None:
        try:
            await ws.send_json(message)
        except Exception:
            self.disconnect(ws)

    async def broadcast(self, message: dict) -> None:
        """广播给所有订阅了该摄像头（或全量订阅）的客户端。"""
        cam = message.get("data", {}).get("camera_id") if message.get("type") == "detection_result" else None
        for ws in list(self.active):
            subs = self.subscriptions.get(ws, set())
            if cam is None or not subs or cam in subs:
                await self.send(ws, message)

    def count(self) -> int:
        return len(self.active)
