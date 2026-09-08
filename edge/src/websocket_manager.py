"""WebSocket 连接管理：实时数据推送的出口（第三期 2.3 重构）。

职责：
- 握手登记与订阅：connect 支持 ?subscribe=cam_a,cam_b（空=全量，向后兼容）；
- 广播隔离：每客户端独立发送队列 + 独立 sender 任务，慢客户端不再拖慢他人；
- 慢消费者治理：单帧发送 wait_for 3s 超时、或队列打满 → 立即摘除该客户端。

inspection_engine 产生检测结果后调用 broadcast()；broadcast 只做入队（非阻塞），
实际 send 由每客户端 sender 任务串行完成——单个客户端卡顿/断开不影响其他客户端
与检测循环。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from fastapi import WebSocket

logger = logging.getLogger("websocket_manager")

# 单帧发送超时：超过即视为慢消费者（不读 socket），摘除（第三期 2.3）
SEND_TIMEOUT_SECONDS = 3.0
# 每客户端待发队列上限：满即摘除（积压说明消费端已跟不上产端）
QUEUE_SIZE = 200


class ConnectionManager:
    def __init__(self, send_timeout: float = SEND_TIMEOUT_SECONDS, queue_size: int = QUEUE_SIZE) -> None:
        self.active: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, set] = {}
        self._queues: Dict[WebSocket, asyncio.Queue] = {}
        self._senders: Dict[WebSocket, asyncio.Task] = {}
        self.send_timeout = send_timeout
        self.queue_size = queue_size

    # ---------- 生命周期 ----------
    async def connect(
        self, ws: WebSocket, camera_id: Optional[str] = None, subscribe: Optional[str] = None
    ) -> None:
        """握手并登记。subscribe 优先于 camera_id：
        - subscribe="cam_a,cam_b"：只接收这两路的 detection_result；
        - subscribe 为空且 camera_id 非空：旧行为，单摄订阅；
        - 两者都空：全量订阅（向后兼容）。
        """
        await ws.accept()
        self.active.append(ws)
        if subscribe is not None:
            subs = {s.strip() for s in subscribe.split(",") if s.strip()}
        else:
            subs = {camera_id} if camera_id else set()
        self.subscriptions[ws] = subs
        self._queues[ws] = asyncio.Queue(maxsize=self.queue_size)
        self._senders[ws] = asyncio.create_task(self._sender_loop(ws))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)
        self.subscriptions.pop(ws, None)
        self._queues.pop(ws, None)
        task = self._senders.pop(ws, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _sender_loop(self, ws: WebSocket) -> None:
        """每客户端串行发送循环：从队列取消息，带超时发送；超时/异常即摘除自己。"""
        q = self._queues.get(ws)
        if q is None:
            return
        while True:
            msg = await q.get()
            try:
                await asyncio.wait_for(ws.send_json(msg), timeout=self.send_timeout)
            except asyncio.TimeoutError:
                logger.warning("WS 客户端发送超时(%.1fs)，摘除慢消费者", self.send_timeout)
                self.disconnect(ws)
                await self._close_quietly(ws)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                self.disconnect(ws)  # 连接已断开等异常：静默摘除
                return

    @staticmethod
    async def _close_quietly(ws: WebSocket) -> None:
        try:
            await ws.close()
        except Exception:
            pass

    # ---------- 发送与广播 ----------
    async def send(self, ws: WebSocket, message: dict) -> None:
        """兼容旧接口：直接入队（有队列时）或原样发送（无队列的边缘场景）。"""
        q = self._queues.get(ws)
        if q is None:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)
            return
        await self._enqueue(ws, q, message)

    async def _enqueue(self, ws: WebSocket, q: asyncio.Queue, message: dict) -> None:
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("WS 客户端队列已满(%d)，摘除慢消费者", self.queue_size)
            self.disconnect(ws)
            await self._close_quietly(ws)

    async def broadcast(self, message: dict) -> None:
        """广播给所有订阅了该摄像头（或全量订阅）的客户端。

        只做非阻塞入队：任何客户端的慢/满/断开都不阻塞广播方与其他客户端。
        """
        cam = message.get("data", {}).get("camera_id") if message.get("type") == "detection_result" else None
        for ws in list(self.active):
            subs = self.subscriptions.get(ws, set())
            if cam is not None and subs and cam not in subs:
                continue  # 该客户端未订阅此摄像头
            q = self._queues.get(ws)
            if q is None:
                continue
            await self._enqueue(ws, q, message)

    def count(self) -> int:
        return len(self.active)
