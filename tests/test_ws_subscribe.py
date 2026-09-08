"""第三期 2.3 WS 订阅接线 + 广播队列验收测试。

覆盖验收标准：
- ① 订阅单摄的客户端收不到其他摄的 detection_result（单元级过滤 + /ws 端点集成）；
- ② 慢客户端不拖慢其他客户端广播：broadcast 只入队不等待；慢消费者（发送超时或
  队列打满）被摘除，其余客户端不受影响。
"""
import asyncio
import threading
import time
import sys
from pathlib import Path

import pytest

EDGE = Path(__file__).resolve().parent.parent / "edge"
if str(EDGE) not in sys.path:
    sys.path.insert(0, str(EDGE))

from src.websocket_manager import ConnectionManager  # noqa: E402


class FakeWS:
    """最小 WebSocket 桩：支持 accept/send_json/close，可控发送延迟与失败。"""

    def __init__(self, name="ws", delay=0.0, fail=False):
        self.name = name
        self.delay = delay
        self.fail = fail
        self.sent = []
        self.closed = False

    async def accept(self):
        pass

    async def send_json(self, msg):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("send failed")
        self.sent.append(msg)

    async def close(self):
        self.closed = True


def _run(coro):
    return asyncio.run(coro)


# ---------- 单元：订阅过滤 ----------
def test_subscribe_filtering():
    """验收①：订阅 cam_001 的客户端不收 cam_002 的 detection_result；全量客户端全收。"""

    async def main():
        m = ConnectionManager()
        sub, full = FakeWS("sub"), FakeWS("full")
        await m.connect(sub, subscribe="cam_001")
        await m.connect(full)  # 无 subscribe=全量
        await m.broadcast({"type": "detection_result", "data": {"camera_id": "cam_002"}})
        await m.broadcast({"type": "detection_result", "data": {"camera_id": "cam_001"}})
        await m.broadcast({"type": "alert", "data": {"ids": [1]}})  # 非检测消息不过滤
        await asyncio.sleep(0.05)  # 等 sender 排空
        return m, sub, full

    m, sub, full = _run(main())
    sub_cams = [x["data"]["camera_id"] for x in sub.sent if x["type"] == "detection_result"]
    full_cams = [x["data"]["camera_id"] for x in full.sent if x["type"] == "detection_result"]
    assert sub_cams == ["cam_001"], sub_cams
    assert full_cams == ["cam_002", "cam_001"], full_cams
    assert any(x["type"] == "alert" for x in sub.sent)


def test_subscribe_multi_camera():
    async def main():
        m = ConnectionManager()
        ws = FakeWS()
        await m.connect(ws, subscribe="cam_001, cam_002")  # 空格容错
        await m.broadcast({"type": "detection_result", "data": {"camera_id": "cam_001"}})
        await m.broadcast({"type": "detection_result", "data": {"camera_id": "cam_003"}})
        await asyncio.sleep(0.05)
        return ws

    ws = _run(main())
    cams = [x["data"]["camera_id"] for x in ws.sent if x["type"] == "detection_result"]
    assert cams == ["cam_001"]


# ---------- 单元：慢消费者治理 ----------
def test_slow_client_removed_without_blocking_others():
    """验收②：慢客户端发送超时被摘除，其他客户端不受拖慢。"""

    async def main():
        m = ConnectionManager(send_timeout=0.1)
        slow, fast = FakeWS("slow", delay=0.5), FakeWS("fast")
        await m.connect(slow)
        await m.connect(fast)
        t0 = time.perf_counter()
        await m.broadcast({"type": "detection_result", "data": {"camera_id": "cam_x"}})
        elapsed = time.perf_counter() - t0
        await asyncio.sleep(0.8)  # 慢端触发 0.1s 超时；快端完成接收
        return m, slow, fast, elapsed

    m, slow, fast, elapsed = _run(main())
    assert elapsed < 0.05, f"broadcast 仅应入队，实测耗时 {elapsed:.3f}s"
    assert len(fast.sent) == 1  # 快客户端正常收到
    assert m.count() == 1 and fast in m.active  # 慢客户端已被摘除
    assert slow.closed


def test_queue_full_removes_client():
    """验收②：队列打满立即摘除（慢消费者积压保护）。"""

    async def main():
        m = ConnectionManager(queue_size=2)
        ws = FakeWS(delay=1.0)  # sender 取走 1 条后阻塞，队列再容 2 条
        await m.connect(ws)
        for _ in range(4):
            await m.broadcast({"type": "ping"})
        return m, ws

    m, ws = _run(main())
    assert m.count() == 0  # 第 4 条入队时队列满 → 摘除
    assert ws.closed


def test_broken_client_removed_silently():
    async def main():
        m = ConnectionManager()
        bad, good = FakeWS(fail=True), FakeWS()
        await m.connect(bad)
        await m.connect(good)
        await m.broadcast({"type": "ping"})
        await asyncio.sleep(0.05)
        return m, good

    m, good = _run(main())
    assert m.count() == 1 and good in m.active
    assert len(good.sent) == 1


# ---------- 集成：/ws 端点 subscribe 参数接线 ----------
def _login(client):
    return client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"}).json()["access_token"]


def test_ws_endpoint_subscribe_filter(client):
    """验收①（集成）：?subscribe=cam_001 的连接收不到 cam_002 的检测帧。"""
    h = {"Authorization": "Bearer " + _login(client)}
    tok = _login(client)
    r = client.post("/api/v1/inspection/start", headers=h, params={"camera_id": "cam_001,cam_002"})
    assert r.status_code == 200, r.text

    received: list = []
    done = threading.Event()

    def reader():
        try:
            with client.websocket_connect(f"/ws?token={tok}&subscribe=cam_001") as ws:
                while not done.is_set():
                    msg = ws.receive_json()
                    if msg.get("type") == "detection_result":
                        received.append(msg["data"]["camera_id"])
                        if len(received) >= 3:
                            return
        except Exception:
            return
        finally:
            done.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(20)
    try:
        client.post("/api/v1/inspection/stop", headers=h)
    except Exception:
        pass
    assert received, "订阅客户端应在时限内收到 cam_001 检测帧"
    assert set(received) == {"cam_001"}, f"订阅过滤失效，收到: {received}"
