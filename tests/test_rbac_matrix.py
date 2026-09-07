"""阶段一安全收口回归（第三期 1.1/1.2/1.3）。

覆盖：
- 1.1 权限矩阵：viewer 全操作 403；operator 可启停/建改普通字段，但删除与凭据/来源修改 403；
  admin 全通过；越权尝试写入审计日志（action=rbac_denied）；WS 控制面与 HTTP 一致（operator 可启停）。
- 1.2 凭据脱敏：API 响应不含明文密码，source 为掩码值（rtsp://user:***@host）；
  内部取流链路保持真实地址；"未修改"的掩码回传不会写穿配置。
- 1.3 WS 一次性票据：换票 → 连接成功；重复使用 → 4401；过期 → 4401；未登录换票 → 401。
"""
import time

import pytest

from main import app


def _login(client, user="admin", pwd="admin123"):
    return client.post("/api/v1/auth/login", json={"username": user, "password": pwd})


def _headers(client, user="admin", pwd="admin123"):
    return {"Authorization": "Bearer " + _login(client, user, pwd).json()["access_token"]}


@pytest.fixture
def operator_client(client):
    """创建 operator 账号并登录（幂等）。"""
    h = _headers(client)
    r = client.post("/api/v1/users", headers=h, json={
        "username": "operator1", "password": "operatorpw", "role": "operator"})
    if r.status_code not in (201, 409):
        pytest.fail(f"创建 operator 失败: {r.status_code} {r.text}")
    tok = _login(client, "operator1", "operatorpw").json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def viewer_client(client):
    """创建 viewer 账号并登录（幂等）。"""
    h = _headers(client)
    r = client.post("/api/v1/users", headers=h, json={
        "username": "viewer1", "password": "viewerpw", "role": "viewer"})
    if r.status_code not in (201, 409):
        pytest.fail(f"创建 viewer 失败: {r.status_code} {r.text}")
    tok = _login(client, "viewer1", "viewerpw").json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


_CRED_CAM = {
    "id": "cam_cred_test",
    "name": "凭据脱敏测试",
    "type": "rtsp",
    "source": "rtsp://192.0.2.1:554/live",
    "username": "camuser",
    "password": "campass123",
}


# ================= 1.1 权限矩阵 =================
def test_viewer_all_mutations_403(client, viewer_client):
    """矩阵格：viewer 对所有操作面 → 403（GET 只读不受限）。"""
    # 只读保持登录即可
    assert client.get("/api/v1/cameras", headers=viewer_client).status_code == 200
    assert client.get("/api/v1/inspection/status", headers=viewer_client).status_code == 200
    # 启停
    assert client.post("/api/v1/inspection/start", headers=viewer_client).status_code == 403
    assert client.post("/api/v1/inspection/stop", headers=viewer_client).status_code == 403
    # 摄像头增删改/active/discover/test
    assert client.post("/api/v1/cameras", headers=viewer_client,
                       json={"id": "cam_v", "name": "x", "type": "simulation", "source": "0"}).status_code == 403
    assert client.put("/api/v1/cameras/cam_001", headers=viewer_client, json={"name": "改"}).status_code == 403
    assert client.delete("/api/v1/cameras/cam_001", headers=viewer_client).status_code == 403
    assert client.put("/api/v1/cameras/cam_001/active", headers=viewer_client).status_code == 403
    assert client.post("/api/v1/cameras/test", headers=viewer_client,
                       json={"source": "0"}).status_code == 403
    assert client.post("/api/v1/cameras/discover", headers=viewer_client,
                       json={"subnet": "192.168.1"}).status_code == 403


def test_operator_start_stop_and_camera_ops(client, operator_client):
    """矩阵格：operator 可启停、可增改普通字段、可设当前，但删除/凭据修改 403。"""
    # 启停（仿真摄像头，秒级完成）
    r = client.post("/api/v1/inspection/start", headers=operator_client)
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/inspection/stop", headers=operator_client)
    assert r.status_code == 200
    # 增
    r = client.post("/api/v1/cameras", headers=operator_client,
                    json={"id": "cam_op_test", "name": "op建", "type": "simulation", "source": "1"})
    assert r.status_code == 201, r.text
    # 改普通字段（名称）
    assert client.put("/api/v1/cameras/cam_op_test", headers=operator_client,
                      json={"name": "op改名"}).status_code == 200
    # 改来源/凭据 → 403
    r = client.put("/api/v1/cameras/cam_op_test", headers=operator_client,
                   json={"source": "rtsp://192.0.2.9:554/x", "username": "u", "password": "p"})
    assert r.status_code == 403
    # 删 → 403
    assert client.delete("/api/v1/cameras/cam_op_test", headers=operator_client).status_code == 403
    # 设当前 → 200
    assert client.put("/api/v1/cameras/cam_op_test/active", headers=operator_client).status_code == 200
    # 无凭据发现 → 200（扫不到设备 count=0）；带凭据发现 → 403
    r = client.post("/api/v1/cameras/discover", headers=operator_client,
                    json={"subnet": "192.0.2", "set_active": False})
    assert r.status_code == 200
    r = client.post("/api/v1/cameras/discover", headers=operator_client,
                    json={"subnet": "192.0.2", "username": "u", "password": "p"})
    assert r.status_code == 403
    # 连接测试（探测失败也返回 200 + ok=false）
    r = client.post("/api/v1/cameras/test", headers=operator_client, json={"source": "0"})
    assert r.status_code == 200
    # 清理（admin）
    client.delete("/api/v1/cameras/cam_op_test", headers=_headers(client))


def test_admin_full_access(client):
    h = _headers(client)
    r = client.post("/api/v1/cameras", headers=h,
                    json={"id": "cam_admin_test", "name": "admin建", "type": "simulation", "source": "1"})
    assert r.status_code == 201
    assert client.put("/api/v1/cameras/cam_admin_test", headers=h, json={"name": "admin改"}).status_code == 200
    assert client.put("/api/v1/cameras/cam_admin_test", headers=h,
                      json={"source": "rtsp://192.0.2.8:554/y", "username": "au", "password": "ap"}).status_code == 200
    assert client.delete("/api/v1/cameras/cam_admin_test", headers=h).status_code == 200


def test_rbac_denied_audited(client, viewer_client):
    """验收④：越权尝试写入审计日志。"""
    client.post("/api/v1/inspection/start", headers=viewer_client)
    r = client.get("/api/v1/audit", headers=_headers(client))
    assert r.status_code == 200
    body = r.json()
    entries = body if isinstance(body, list) else body.get("items") or body.get("records") or []
    assert any(e.get("action") == "rbac_denied" for e in entries), "越权尝试应记录审计"


def test_ws_operator_can_control(client, operator_client):
    """矩阵格：WS 控制面与 HTTP 一致 —— operator 可启停（原 admin-only 放宽）。"""
    tok = operator_client["Authorization"].split(" ")[1]
    with client.websocket_connect(f"/ws?token={tok}") as ws:
        ws.send_json({"action": "start", "camera_id": "cam_001"})
        msg = ws.receive_json()
        assert msg.get("type") == "control" and msg.get("status") == "ok", msg
        ws.send_json({"action": "stop"})
        msg = ws.receive_json()
        assert msg.get("type") == "control" and msg.get("status") == "ok", msg


# ================= 1.2 凭据脱敏 =================
def test_camera_credentials_masked_in_responses(client, viewer_client):
    """验收①：任意登录用户（viewer 亦可）GET /cameras 响应不含明文密码。"""
    h = _headers(client)
    r = client.post("/api/v1/cameras", headers=h, json=_CRED_CAM)
    assert r.status_code == 201, r.text
    assert "campass123" not in r.text, "创建响应不得含明文密码"
    assert r.json()["source"] == "rtsp://camuser:***@192.0.2.1:554/live"
    # viewer 视角同样脱敏
    r = client.get("/api/v1/cameras", headers=viewer_client)
    assert r.status_code == 200
    assert "campass123" not in r.text, "列表响应不得含明文密码"
    r = client.get("/api/v1/cameras/cam_cred_test", headers=viewer_client)
    assert r.status_code == 200
    assert "campass123" not in r.text
    assert r.json()["source_masked"] == "rtsp://camuser:***@192.0.2.1:554/live"


def test_masking_does_not_break_internal_stream_path(client):
    """内部链路（取流/检测）仍使用真实 source：API 脱敏只发生在响应层。"""
    client.post("/api/v1/cameras", headers=_headers(client), json=_CRED_CAM)
    internal = client.app.state.cam.get("cam_cred_test")
    assert internal is not None
    assert "campass123" in internal.source, "内部对象必须保留真实取流地址"
    cfg = next(c for c in client.app.state.cm.get().cameras if c.id == "cam_cred_test")
    assert cfg.password == "campass123"


def test_masked_source_roundtrip_does_not_corrupt(client):
    """前端把掩码值原样回传（"未修改"）时不得写穿配置。"""
    h = _headers(client)
    client.post("/api/v1/cameras", headers=h, json=_CRED_CAM)
    r = client.put("/api/v1/cameras/cam_cred_test", headers=h,
                   json={"source": "rtsp://camuser:***@192.0.2.1:554/live", "name": "改名不改源"})
    assert r.status_code == 200
    cfg = next(c for c in client.app.state.cm.get().cameras if c.id == "cam_cred_test")
    assert cfg.source == "rtsp://camuser:campass123@192.0.2.1:554/live", "掩码回传不应覆盖真实地址"
    assert cfg.password == "campass123"
    assert client.app.state.cam.get("cam_cred_test").name == "改名不改源"


# ================= 1.3 WS 一次性票据 =================
def _ws_token(client, user="admin", pwd="admin123"):
    return _login(client, user, pwd).json()["access_token"]


def test_ws_ticket_issue_requires_login(client):
    assert client.post("/api/v1/ws-ticket").status_code == 401


def test_ws_ticket_flow(client):
    """验收：换票 → 连接成功并可控制；重复使用 → 4401。"""
    tok = _ws_token(client)
    r = client.post("/api/v1/ws-ticket", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    body = r.json()
    assert body["ttl"] == 30 and body["ticket"]
    ticket = body["ticket"]
    # 首次使用：连接成功，operator/admin 身份可启停
    with client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        ws.send_json({"action": "start", "camera_id": "cam_001"})
        msg = ws.receive_json()
        assert msg.get("type") == "control" and msg.get("status") == "ok", msg
        ws.send_json({"action": "stop"})
        ws.receive_json()
    # 重复使用（一次性）→ 4401
    with client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        msg = ws.receive_json()
        assert msg.get("code") == 4401


def test_ws_ticket_expired(client):
    """验收：过期 → 4401。"""
    tok = _ws_token(client)
    ticket = client.post("/api/v1/ws-ticket", headers={"Authorization": f"Bearer {tok}"}).json()["ticket"]
    store = app.state.stream_tickets
    store[ticket]["exp"] = time.time() - 1  # 直接把有效期拨到过去（避免真实等待 30s）
    with client.websocket_connect(f"/ws?ticket={ticket}") as ws:
        msg = ws.receive_json()
        assert msg.get("code") == 4401


def test_ws_ticket_invalid(client):
    with client.websocket_connect("/ws?ticket=not-a-real-ticket") as ws:
        assert ws.receive_json().get("code") == 4401
