"""端到端集成测试：验证后端真实可运行、模块间真实互联。

运行方式（项目根目录）：
    .venv/Scripts/python.exe -m pytest tests/test_api.py -v

覆盖维度：
- 服务可用性（/ 与 /api/v1/health）
- 模块契约正确性（摄像头/配置/系统健康/模型）
- 实时链路：WebSocket 指令驱动 -> 检测循环 -> 结果广播 -> 数据库持久化
- 跨模块数据流转：检测结果可被查询与统计（证明 detector->db->api 全链路打通）
"""
import json
import sys
from pathlib import Path

import pytest

EDGE = Path(__file__).resolve().parent.parent / "edge"
if str(EDGE) not in sys.path:
    sys.path.insert(0, str(EDGE))

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["service"] == "ai-visual-inspection"


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "websocket_clients" in body


def test_cameras_list(client):
    r = client.get("/api/v1/cameras", headers=_headers(client))
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) >= 1
    assert all("id" in c and "type" in c for c in data)


def test_camera_detail_and_404(client):
    r = client.get("/api/v1/cameras/cam_001", headers=_headers(client))
    assert r.status_code == 200
    assert r.json()["id"] == "cam_001"
    assert client.get("/api/v1/cameras/__nope__", headers=_headers(client)).status_code == 404


def test_network_scan_endpoint(client):
    r = client.get("/api/v1/cameras/network/scan", params={"subnet": "192.168.1"}, headers=_headers(client))
    assert r.status_code == 200
    assert "found" in r.json()


def test_config_get_and_update(client):
    r = client.get("/api/v1/config", headers=_headers(client))
    assert r.status_code == 200
    r2 = client.put("/api/v1/config", json={"confidence_threshold": 0.72}, headers=_headers(client))
    assert r2.status_code == 200
    assert r2.json()["confidence_threshold"] == 0.72


def test_system_health_contract(client):
    r = client.get("/api/v1/system-health", headers=_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("healthy", "warning", "critical")
    assert "cpu_percent" in body


def test_model_versions_contract(client):
    r = client.get("/api/v1/model-versions", headers=_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "active_id" in body
    assert isinstance(body["items"], list)


def test_inspection_websocket_to_persistence(client):
    """核心跨模块链路验证：WS 启动 -> 实时推送 -> 数据库持久化 -> 可查询/统计。"""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "start", "camera_id": "cam_001"})
        ctrl = ws.receive_json()
        assert ctrl["type"] == "control" and ctrl["status"] == "ok"

        got = None
        for _ in range(8):
            data = ws.receive_json()
            if data.get("type") == "detection_result":
                got = data
                break
        assert got is not None, "未收到检测结果实时推送"
        assert "data" in got and "defect_count" in got["data"]
        ws.send_json({"action": "stop"})

    # 验证持久化（detector -> database 链路）
    h = _headers(client)
    r = client.get("/api/v1/detection-results", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1

    stats = client.get("/api/v1/detection-results/statistics", headers=h)
    assert stats.status_code == 200
    assert stats.json()["total"] >= 1


# ---------- 认证与权限 ----------
def _login(client, user="admin", pwd="admin123"):
    r = client.post("/api/v1/auth/login", json={"username": user, "password": pwd})
    return r


def _headers(client, user="admin", pwd="admin123"):
    return {"Authorization": "Bearer " + _login(client, user, pwd).json()["access_token"]}


def test_login_success_and_token(client):
    r = _login(client)
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body and body["user"]["username"] == "admin"


def test_login_wrong_password(client):
    r = _login(client, pwd="wrong")
    assert r.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    tok = _login(client).json()["access_token"]
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and r.json()["username"] == "admin"


def test_protected_requires_token(client):
    for path in ("/api/v1/cameras", "/api/v1/config", "/api/v1/detection-results",
                 "/api/v1/system-health", "/api/v1/reports/summary", "/api/v1/users"):
        assert client.get(path).status_code == 401


def test_bad_token_rejected(client):
    assert client.get("/api/v1/cameras", headers={"Authorization": "Bearer garbage"}).status_code == 401


# ---------- 摄像头 CRUD ----------
def test_camera_crud(client):
    tok = _login(client).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    r = client.post("/api/v1/cameras", headers=h, json={"id": "cam_new", "name": "新摄像头", "type": "usb", "source": "1"})
    assert r.status_code == 201 and r.json()["id"] == "cam_new"
    # 重复 id 冲突
    assert client.post("/api/v1/cameras", headers=h, json={"id": "cam_new", "name": "x"}).status_code == 409
    r = client.put("/api/v1/cameras/cam_new", headers=h, json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert client.delete("/api/v1/cameras/cam_new", headers=h).status_code == 200
    assert client.get("/api/v1/cameras/cam_new", headers=h).status_code == 404


# ---------- 告警规则 + 事件 ----------
def test_alert_rule_and_event(client):
    tok = _login(client).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    # 阈值设为 0，确保每次检测都触发告警
    rr = client.post("/api/v1/alerts/rules", headers=h, json={
        "name": "强制告警", "metric": "defect_rate", "operator": "ge", "threshold": 0.0})
    assert rr.status_code == 201
    rule_id = rr.json()["id"]
    # 启动检测，触发告警
    client.post("/api/v1/inspection/start", headers=h)
    import time
    time.sleep(2)
    client.post("/api/v1/inspection/stop", headers=h)
    ev = client.get("/api/v1/alerts/events", headers=h)
    assert ev.status_code == 200
    assert ev.json()["total"] >= 1
    eid = ev.json()["items"][0]["id"]
    assert client.post(f"/api/v1/alerts/events/{eid}/acknowledge", headers=h).status_code == 200
    assert client.delete(f"/api/v1/alerts/rules/{rule_id}", headers=h).status_code == 200


# ---------- 报表 + 导出 ----------
def test_reports_summary_and_export(client):
    tok = _login(client).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    s = client.get("/api/v1/reports/summary", headers=h)
    assert s.status_code == 200 and "by_type" in s.json() and "trend" in s.json()
    ex = client.get("/api/v1/reports/export?format=excel", headers=h)
    assert ex.status_code == 200
    assert ex.headers["content-type"].find("spreadsheet") >= 0


# ---------- 模型版本（上传/激活/删除） ----------
def test_model_version_upload_activate_delete(client):
    tok = _login(client).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    import io
    # 使用测试专用文件名，避免污染模型目录或与真实权重（yolov8n.pt）冲突
    files = {"file": ("_upload_test_dummy.pt", io.BytesIO(b"dummy model weights"), "application/octet-stream")}
    data = {"name": "v1", "version": "1.0.0", "metric": 0.9, "description": "test", "activate": "false"}
    r = client.post("/api/v1/model-versions/upload", headers=h, files=files, data=data)
    assert r.status_code == 201
    mv_id = r.json()["id"]
    fp = r.json().get("file_path")
    try:
        assert client.post(f"/api/v1/model-versions/{mv_id}/activate", headers=h).status_code == 200
        assert client.get("/api/v1/model-versions", headers=h).json()["active_id"] == mv_id
        assert client.delete(f"/api/v1/model-versions/{mv_id}", headers=h).status_code == 200
    finally:
        # 确保测试产生的权重文件被清理，避免遗留占位文件干扰其他用例
        if fp:
            try:
                import os
                os.remove(fp)
            except OSError:
                pass


# ---------- 用户管理（admin） ----------
def test_user_crud_requires_admin(client):
    # 创建一个 operator，用其令牌访问 users 应 403
    tok = _login(client).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    uid = client.post("/api/v1/users", headers=h, json={
        "username": "op1", "password": "pw", "role": "operator"}).json()["id"]
    op_tok = client.post("/api/v1/auth/login", json={"username": "op1", "password": "pw"}).json()["access_token"]
    oh = {"Authorization": f"Bearer {op_tok}"}
    assert client.get("/api/v1/users", headers=oh).status_code == 403
    # admin 可列
    assert client.get("/api/v1/users", headers=h).status_code == 200
    # 删除
    assert client.delete(f"/api/v1/users/{uid}", headers=h).status_code == 200


# ---------- REST 检测控制 ----------
def test_inspection_rest_control(client):
    tok = _login(client).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.post("/api/v1/inspection/start", headers=h).status_code == 200
    import time
    time.sleep(1)
    st = client.get("/api/v1/inspection/status", headers=h).json()
    assert st["running"] is True
    assert client.post("/api/v1/inspection/stop", headers=h).status_code == 200
    assert client.get("/api/v1/inspection/status", headers=h).json()["running"] is False

