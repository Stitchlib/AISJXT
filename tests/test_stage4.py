"""阶段四功能完整性验收测试：M6 / M8 / M12 / L3 / L9。

依赖 conftest 注入的共享 `client`（临时配置 + 临时库，测试隔离）。
注意：AuthService 在每个 TestClient 上下文重建，失败计数不跨用例持久，
因此登录限流必须在单个用例内完成 5 次失败 + 1 次正确。
"""
from pathlib import Path

from fastapi.testclient import TestClient  # noqa: F401  (conftest 已注入 sys.path)


def _login(client: TestClient, username="admin", password="admin123"):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _admin(client: TestClient):
    return {"Authorization": f"Bearer {_login(client)}"}


def _ensure_user(client, headers, username, password, role):
    """幂等创建用户（已存在则忽略 409）。"""
    r = client.post(
        "/api/v1/users",
        headers=headers,
        json={"username": username, "password": password, "role": role},
    )
    if r.status_code not in (201, 409):
        raise AssertionError(f"创建用户异常 {r.status_code}: {r.text}")


# ---------------- M6 用户体系补全 ----------------

def test_change_own_password_requires_old(client: TestClient):
    _ensure_user(client, _admin(client), "m6_pw", "m6_pw_123", "operator")
    tok = _login(client, "m6_pw", "m6_pw_123")
    h = {"Authorization": f"Bearer {tok}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    uid = me["id"]
    # 本人改密不提供旧口令 -> 400
    r = client.put(f"/api/v1/users/{uid}/password", headers=h, json={"new_password": "newpass1"})
    assert r.status_code == 400, r.text
    # 提供正确旧口令 -> 200，且新口令可登录
    r = client.put(
        f"/api/v1/users/{uid}/password",
        headers=h,
        json={"old_password": "m6_pw_123", "new_password": "newpass1"},
    )
    assert r.status_code == 200, r.text
    assert _login(client, "m6_pw", "newpass1")  # 用新口令可登录


def test_admin_change_other_password_no_old_required(client: TestClient):
    _ensure_user(client, _admin(client), "m6_other", "other123", "operator")
    admin = _admin(client)
    # 找到该用户 id
    uid = next(u["id"] for u in client.get("/api/v1/users", headers=admin).json() if u["username"] == "m6_other")
    r = client.put(f"/api/v1/users/{uid}/password", headers=admin, json={"new_password": "other456"})
    assert r.status_code == 200, r.text
    assert _login(client, "m6_other", "other456")


def test_delete_self_blocked(client: TestClient):
    admin = _admin(client)
    uid = client.get("/api/v1/auth/me", headers=admin).json()["id"]
    r = client.delete(f"/api/v1/users/{uid}", headers=admin)
    assert r.status_code == 400, r.text


def test_delete_last_admin_blocked(client: TestClient):
    admin = _admin(client)
    # 确保系统内仅一个 admin
    admins = [u for u in client.get("/api/v1/users", headers=admin).json() if u["role"] == "admin"]
    assert len(admins) == 1
    r = client.delete(f"/api/v1/users/{admins[0]['id']}", headers=admin)
    assert r.status_code == 400, r.text


def test_login_rate_limit(client: TestClient):
    _ensure_user(client, _admin(client), "m6_rl", "rl12345", "operator")
    # 5 次错误口令 -> 全部 401
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"username": "m6_rl", "password": "wrong"})
        assert r.status_code == 401, r.text
    # 第 6 次正确口令 -> 因锁定而 401
    r = client.post("/api/v1/auth/login", json={"username": "m6_rl", "password": "rl12345"})
    assert r.status_code == 401, r.text


# ---------------- M8 CORS 收敛 ----------------

def test_cors_default_rejects_cross_origin(client: TestClient):
    # 跨域请求：默认 allow_origins 为空（仅同源），不应回写 Access-Control-Allow-Origin
    r = client.get("/", headers={"Origin": "http://evil.example.com"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}


def test_cors_same_origin_functional(client: TestClient):
    # 无 Origin 的正常请求不受影响
    assert client.get("/").status_code == 200


# ---------------- M12 配置健壮性 ----------------

def test_corrupt_config_backup_and_degraded(client: TestClient):
    from src.config_manager import ConfigManager

    good_path = ConfigManager._resolve_path()  # 指向 conftest 的临时好配置
    d = Path(__file__).resolve().parent.parent / "tests" / "_tmp_cfg"
    d.mkdir(parents=True, exist_ok=True)
    corrupt = d / "config.json"
    corrupt.write_text("{ this is not valid json ,,,", encoding="utf-8")
    try:
        cm = ConfigManager(path=corrupt)
        assert cm.is_degraded() is True
        assert cm.degraded_reason()
        backups = list(d.glob("config.json.corrupt-*"))
        assert backups, "损坏配置应备份为 config.json.corrupt-*"
    finally:
        # 复原单例，避免污染后续用例的 app.state.cm
        ConfigManager(path=good_path)
        for b in d.glob("config.json.corrupt-*"):
            try:
                b.unlink()
            except OSError:
                pass


def test_system_health_exposes_config_degraded(client: TestClient):
    admin = _admin(client)
    r = client.get("/api/v1/system-health", headers=admin)
    assert r.status_code == 200, r.text
    assert "config_degraded" in r.json()
    assert isinstance(r.json()["config_degraded"], bool)


# ---------------- L3 审计日志 ----------------

def test_audit_login_recorded_and_admin_only(client: TestClient):
    # 登录动作应被记录
    _login(client)  # admin 登录
    admin = _admin(client)
    r = client.get("/api/v1/audit", headers=admin)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert isinstance(items, list) and len(items) > 0
    assert any(it["action"] == "auth.login" for it in items)

    # viewer 不可访问审计接口（403）
    _ensure_user(client, admin, "m6_viewer", "viewer123", "viewer")
    vtok = _login(client, "m6_viewer", "viewer123")
    vr = client.get("/api/v1/audit", headers={"Authorization": f"Bearer {vtok}"})
    assert vr.status_code == 403, vr.text


# ---------------- L9 监控补强 ----------------

def test_system_health_business_metrics(client: TestClient):
    admin = _admin(client)
    r = client.get("/api/v1/system-health", headers=admin)
    assert r.status_code == 200, r.text
    h = r.json()
    lat = h["inference_latency_ms"]
    assert isinstance(lat, dict) and "p50" in lat and "p95" in lat
    assert isinstance(h["frame_drop_rate"], (int, float))
    assert isinstance(h["websocket_clients"], int)
    assert isinstance(h["db_size_mb"], (int, float))
    assert isinstance(h["write_qps"], (int, float))
