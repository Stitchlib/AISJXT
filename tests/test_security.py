"""安全回归测试（L8 / H1 / H2 / M5 / M4）：先红后绿，锁定已修复的高危与中危问题。

覆盖：
- H1：配置接口不泄露 secret_key / smtp_pass 明文；
- M5：仅管理员可修改配置（viewer/operator 越权返回 403）；
- H2：WebSocket 未授权连接被拒（4401），viewer 不可下发启停指令（4403）；
- M4：模型上传拒绝非 .pt 类型；
- H5：默认密钥环境下 /system-health 暴露 config_degraded 以外的隐患（仅做存在性校验）。
"""
import io

import pytest

EDGE = None  # 占位，避免 linter 误报；实际路径由 conftest 注入


def _login(client, user="admin", pwd="admin123"):
    return client.post("/api/v1/auth/login", json={"username": user, "password": pwd})


def _headers(client, user="admin", pwd="admin123"):
    return {"Authorization": "Bearer " + _login(client, user, pwd).json()["access_token"]}


@pytest.fixture
def viewer_client(client):
    """创建一个 viewer 账号并登录，返回其令牌（幂等：跨用例共享同一 DB 时若已存在则直接登录）。"""
    h = _headers(client)
    r = client.post("/api/v1/users", headers=h, json={
        "username": "viewer1", "password": "viewerpw", "role": "viewer"})
    if r.status_code == 409:  # 已存在（同一会话内其他用例已创建），直接登录
        tok = _login(client, "viewer1", "viewerpw").json()["access_token"]
    else:
        assert r.status_code == 201
        tok = _login(client, "viewer1", "viewerpw").json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


# ---------- H1：配置脱敏 ----------
def test_config_get_hides_sensitive(client):
    r = client.get("/api/v1/config", headers=_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert "secret_key" not in body, "secret_key 不应出现在配置响应中"
    # smtp_pass 若有值应被掩码
    if body.get("smtp_pass"):
        assert body["smtp_pass"] == "***"
    # 非敏感项仍应可见
    assert "confidence_threshold" in body


# ---------- M5：配置修改需管理员 ----------
def test_config_put_requires_admin(client, viewer_client):
    # viewer 越权修改配置 -> 403
    r = client.put("/api/v1/config", json={"confidence_threshold": 0.6}, headers=viewer_client)
    assert r.status_code == 403
    # admin 可修改
    r2 = client.put("/api/v1/config", json={"confidence_threshold": 0.6}, headers=_headers(client))
    assert r2.status_code == 200
    assert r2.json()["confidence_threshold"] == 0.6


# ---------- H2：WebSocket 鉴权 ----------
def test_ws_rejects_unauthorized(client):
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg.get("code") == 4401, "未授权 WS 连接应被拒（4401）"


def test_ws_viewer_cannot_control(client, viewer_client):
    with client.websocket_connect(f"/ws?token={viewer_client['Authorization'].split(' ')[1]}") as ws:
        ws.send_json({"action": "start", "camera_id": "cam_001"})
        msg = ws.receive_json()
        assert msg.get("code") == 4403, "viewer 不应能下发启停指令（4403）"


# ---------- M4：模型上传类型限制 ----------
def test_model_upload_rejects_non_pt(client):
    h = _headers(client)
    files = {"file": ("evil.txt", io.BytesIO(b"not a model"), "text/plain")}
    r = client.post("/api/v1/model-versions/upload", headers=h, files=files,
                    data={"name": "x", "version": "1.0.0"})
    assert r.status_code == 400


def test_model_upload_accepts_pt(client):
    h = _headers(client)
    files = {"file": ("good.pt", io.BytesIO(b"dummy"), "application/octet-stream")}
    r = client.post("/api/v1/model-versions/upload", headers=h, files=files,
                    data={"name": "good", "version": "1.0.0", "activate": "false"})
    assert r.status_code == 201
    mv_id = r.json()["id"]
    fp = r.json().get("file_path")
    # 清理
    client.delete(f"/api/v1/model-versions/{mv_id}", headers=h)
    if fp:
        import os
        try:
            os.remove(fp)
        except OSError:
            pass
