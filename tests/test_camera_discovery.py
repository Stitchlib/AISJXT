"""网络摄像头自动发现 + 注册 单元测试。

运行（项目根目录）：
    .venv/Scripts/python.exe -m pytest tests/test_camera_discovery.py -v

要点：
- build_rtsp_candidates 构造常见厂商 RTSP URL（匿名/带账号）。
- discover_and_add 在 mock 网络环境下验证：扫描 -> 探测 -> 注册 -> 写入配置 -> 设为当前。
- API 层：POST /cameras/discover 与 PUT /cameras/{id}/active 端到端验证。
- inspection_engine 在显式指定为空时优先使用配置 active_camera_id。
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

EDGE = Path(__file__).resolve().parent.parent / "edge"
if str(EDGE) not in sys.path:
    sys.path.insert(0, str(EDGE))

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from src.camera_manager import CameraManager  # noqa: E402
from src.inspection_engine import InspectionEngine  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_build_rtsp_candidates():
    urls = CameraManager.build_rtsp_candidates("192.168.1.50")
    assert any(u == "rtsp://192.168.1.50:554" for u in urls)
    assert any("rtsp://192.168.1.50:554/Streaming/Channels/101" in u for u in urls)
    assert any("rtsp://192.168.1.50:554/cam/realmonitor" in u for u in urls)
    with_auth = CameraManager.build_rtsp_candidates("192.168.1.50", "admin", "12345")
    assert any("rtsp://admin:12345@192.168.1.50:554" in u for u in with_auth)


def test_discover_and_add_registers(monkeypatch):
    cm = CameraManager()
    monkeypatch.setattr(cm, "scan_network", lambda subnet, ports: [{"host": "192.168.1.50", "port": 554}])
    monkeypatch.setattr("src.camera_capture.probe_source", lambda url, timeout=5.0: True)

    added = cm.discover_and_add(subnet="192.168.1", set_active=True)
    assert len(added) == 1
    cam = added[0]
    assert cam.id == "cam_net_192_168_1_50"
    assert cam.type.value == "network"
    assert "192.168.1.50" in cam.source

    # 配置内存态与持久化文件均反映注册 + 激活
    assert cm._cm.get().active_camera_id == "cam_net_192_168_1_50"
    saved = json.loads(Path(cm._cm.path).read_text(encoding="utf-8"))
    assert any(c["id"] == "cam_net_192_168_1_50" for c in saved["cameras"])
    assert saved["active_camera_id"] == "cam_net_192_168_1_50"


def test_discover_no_camera_returns_empty(monkeypatch):
    cm = CameraManager()
    monkeypatch.setattr(cm, "scan_network", lambda subnet, ports: [])
    monkeypatch.setattr("src.camera_capture.probe_source", lambda url, timeout=5.0: False)
    assert cm.discover_and_add() == []


def _login(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    return r.json()["access_token"]


def test_discover_and_set_active_via_api(client, monkeypatch):
    # 让扫描瞬时返回、探测恒成功，使 API 路径可测且不触碰真实网络
    monkeypatch.setattr(app.state.cam, "scan_network", lambda subnet, ports: [{"host": "192.168.1.77", "port": 554}])
    monkeypatch.setattr("src.camera_capture.probe_source", lambda url, timeout=5.0: True)

    tok = _login(client)
    h = {"Authorization": f"Bearer {tok}"}
    r = client.post("/api/v1/cameras/discover", json={"subnet": "192.168.1", "set_active": True}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1

    cfg = client.get("/api/v1/config", headers=h).json()
    assert cfg["active_camera_id"] == "cam_net_192_168_1_77"


def test_engine_uses_active_camera(monkeypatch):
    class FakeDet:
        is_simulation = True

    class FakeDB:
        def insert_result(self, *a, **k):
            return 1

    class FakeWS:
        async def broadcast(self, *a, **k):
            pass

    monkeypatch.setattr("src.inspection_engine.build_detector", lambda cfg: FakeDet())
    cm = CameraManager()._cm
    cm.config.active_camera_id = "cam_002"
    eng = InspectionEngine(cm, FakeDB(), FakeWS(), CameraManager())

    async def fake_loop(*a, **k):
        return None

    monkeypatch.setattr(eng, "_loop", fake_loop)  # 不真正跑检测循环

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(eng.start(camera_id=None))
        assert eng.active_camera_id == "cam_002"
        loop.run_until_complete(eng.stop())
    finally:
        loop.close()
