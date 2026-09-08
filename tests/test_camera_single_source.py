"""第三期 3.1 配置单一数据源：摄像头 API 契约快照测试。

在把 CameraManager 改造为 ConfigManager 的派生视图（删除 cameras.py 双写）之前，
先用本文件固定当前对外契约与三方一致性（API 响应 / 内存视图 / 配置文件）。
重构后复跑本文件，全部断言不变即视为契约未破坏。

快照要点：
- 新增：响应脱敏（source 含 :***@），配置文件存真实鉴权地址，内存视图与配置一致
- 更新：名称/启用/ROI/状态改动三方同步；掩码 source 回传视为不修改
- 凭据更新：配置持久化新鉴权地址，内部取流地址同步
- 删除：API/内存/配置三方同时消失；删除激活摄像头时 active_camera_id 清空
- 激活：配置 active_camera_id 落盘，GET 显示 status=online
"""
import json
from pathlib import Path

import pytest

EDGE = Path(__file__).resolve().parent.parent / "edge"
if str(EDGE) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(EDGE))


def _login(client, user="admin", pwd="admin123"):
    r = client.post("/api/v1/auth/login", json={"username": user, "password": pwd})
    return r.json()["access_token"]


def _headers(client, user="admin", pwd="admin123"):
    return {"Authorization": "Bearer " + _login(client, user, pwd)}


def _cfg_raw(client) -> dict:
    """直接读配置文件（单一数据源的最终落盘形态）。"""
    return json.loads(Path(client.app.state.cm.path).read_text(encoding="utf-8"))


def _cfg_cam(client, cam_id: str) -> dict | None:
    for c in _cfg_raw(client)["cameras"]:
        if c["id"] == cam_id:
            return c
    return None


def _assert_three_views_consistent(client, cam_id: str) -> dict:
    """API 详情 / 内部视图 / 配置文件 三方一致（source 以配置为唯一真值）。"""
    h = _headers(client)
    r = client.get(f"/api/v1/cameras/{cam_id}", headers=h)
    assert r.status_code == 200, r.text
    api = r.json()
    cam = client.app.state.cam.get(cam_id)
    assert cam is not None, "内存视图缺少该摄像头"
    cfg = _cfg_cam(client, cam_id)
    assert cfg is not None, "配置文件缺少该摄像头"
    # 内部视图与配置文件的持久化字段一致
    assert cam.source == cfg["source"], "内部 source 与配置不一致（双写漂移）"
    assert cam.name == cfg["name"]
    assert cam.enabled == cfg["enabled"]
    def _norm_roi(items):
        return [i.model_dump() if hasattr(i, "model_dump") else dict(i) for i in items]
    assert _norm_roi(cam.roi) == _norm_roi(cfg.get("roi", [])), "内部 roi 与配置不一致"
    # API 响应脱敏：明文凭据不外泄，source_masked 与 source 脱敏后一致
    assert ":***@" in api["source"] or api["source"] == cfg["source"], "API source 应脱敏或无凭据"
    assert api["source_masked"] == api["source"], "source_masked 应与脱敏后的 source 一致"
    assert cfg["source"] == cam.source
    return cfg


def test_add_camera_snapshot(client):
    """新增：响应脱敏 + 配置持久化鉴权地址 + 内部/配置一致。"""
    h = _headers(client)
    cid = "snap_add_001"
    try:
        r = client.post("/api/v1/cameras", headers=h, json={
            "id": cid, "name": "快照新增", "source": "rtsp://192.0.2.9:554/live",
            "username": "u1", "password": "p1",
        })
        assert r.status_code == 201, r.text
        body = r.json()
        # 响应脱敏：明文密码不出现在任何字段
        assert "p1" not in body["source"]
        assert body["source_masked"].startswith("rtsp://u1:***@")
        # 配置文件：存的是注入凭据后的真实取流地址（内部链路取流依赖）
        cfg = _cfg_cam(client, cid)
        assert cfg is not None
        assert "u1:p1@" in cfg["source"], "配置应保存注入凭据后的真实地址"
        # 内部视图与配置一致
        assert _assert_three_views_consistent(client, cid)
    finally:
        client.delete(f"/api/v1/cameras/{cid}", headers=h)


def test_add_duplicate_returns_409_and_no_drift(client):
    """重复 id 409；且内存/配置都不产生半写状态。"""
    h = _headers(client)
    cid = "snap_dup_001"
    try:
        r1 = client.post("/api/v1/cameras", headers=h, json={
            "id": cid, "name": "首建", "source": "0",
        })
        assert r1.status_code == 201, r1.text
        r2 = client.post("/api/v1/cameras", headers=h, json={
            "id": cid, "name": "重复", "source": "1",
        })
        assert r2.status_code == 409
        # 三方视图仍然只有一份该摄像头，且字段为首次写入值
        assert _assert_three_views_consistent(client, cid)
        assert client.get(f"/api/v1/cameras/{cid}", headers=h).json()["name"] == "首建"
    finally:
        client.delete(f"/api/v1/cameras/{cid}", headers=h)


def test_update_basic_fields_snapshot(client):
    """名称/启用/ROI 更新：API、内存、配置三方同步。"""
    h = _headers(client)
    cid = "snap_upd_001"
    try:
        r = client.post("/api/v1/cameras", headers=h, json={
            "id": cid, "name": "原名", "source": "0",
        })
        assert r.status_code == 201, r.text

        r = client.put(f"/api/v1/cameras/{cid}", headers=h, json={
            "name": "新名", "enabled": False,
            "roi": [{"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "新名"
        assert body["enabled"] is False
        assert body["roi"] == [{"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}]

        cfg = _assert_three_views_consistent(client, cid)
        assert cfg["name"] == "新名"
        assert cfg["enabled"] is False
        assert cfg["roi"] == [{"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}], "ROI 应持久化到配置"
    finally:
        client.delete(f"/api/v1/cameras/{cid}", headers=h)


def test_update_credentials_persist_snapshot(client):
    """凭据更新（admin）：配置持久化新鉴权地址；掩码回传=不修改；operator 拒绝。"""
    h = _headers(client)
    cid = "snap_cred_001"
    try:
        r = client.post("/api/v1/cameras", headers=h, json={
            "id": cid, "name": "凭据快照", "source": "rtsp://192.0.2.10:554/a",
            "username": "old", "password": "oldp",
        })
        assert r.status_code == 201, r.text
        old_cfg = _cfg_cam(client, cid)
        assert "old:oldp@" in old_cfg["source"]

        # ① 前端把未修改的 source 以掩码值回传 → 视为不修改，配置不被写穿
        r = client.put(f"/api/v1/cameras/{cid}", headers=h, json={
            "name": "改名不改源", "source": "rtsp://old:***@192.0.2.10:554/a",
        })
        assert r.status_code == 200, r.text
        cfg = _cfg_cam(client, cid)
        assert cfg["source"] == old_cfg["source"], "掩码 source 回传不得写穿配置"
        assert cfg["name"] == "改名不改源"

        # ② 显式换凭据（admin）：配置持久化新鉴权地址，内部取流地址同步
        r = client.put(f"/api/v1/cameras/{cid}", headers=h, json={
            "username": "new", "password": "newp",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert "newp" not in json.dumps(body), "响应不得泄漏明文密码"
        cfg = _cfg_cam(client, cid)
        assert "new:newp@" in cfg["source"], "新凭据应注入并持久化"
        assert "oldp" not in cfg["source"]
        _assert_three_views_consistent(client, cid)

        # ③ operator 修改来源/凭据 → 403（权限矩阵，快照防回归）
        cr = client.post("/api/v1/users", headers=h, json={
            "username": "operator1", "password": "operatorpw", "role": "operator"})
        assert cr.status_code in (201, 409), cr.text  # 幂等：已存在不报错
        oh = _headers(client, "operator1", "operatorpw")
        r = client.put(f"/api/v1/cameras/{cid}", headers=oh, json={"source": "rtsp://192.0.2.99/x"})
        assert r.status_code == 403
    finally:
        client.delete(f"/api/v1/cameras/{cid}", headers=h)


def test_delete_snapshot(client):
    """删除：API/内存/配置三方同时消失；删除激活摄像头时 active_camera_id 清空。"""
    h = _headers(client)
    cid = "snap_del_001"
    r = client.post("/api/v1/cameras", headers=h, json={
        "id": cid, "name": "待删", "source": "0",
    })
    assert r.status_code == 201, r.text
    # 置为激活后删除，验证 active 指针清理
    ra = client.put(f"/api/v1/cameras/{cid}/active", headers=h)
    assert ra.status_code == 200, ra.text

    rd = client.delete(f"/api/v1/cameras/{cid}", headers=h)
    assert rd.status_code == 200, rd.text

    assert client.get(f"/api/v1/cameras/{cid}", headers=h).status_code == 404
    assert client.app.state.cam.get(cid) is None, "内存视图应同步删除"
    assert _cfg_cam(client, cid) is None, "配置文件应同步删除"
    raw = _cfg_raw(client)
    assert raw["active_camera_id"] != cid, "删除激活摄像头后 active 指针应清理"
    # 二次删除 404
    assert client.delete(f"/api/v1/cameras/{cid}", headers=h).status_code == 404


def test_activate_snapshot(client):
    """激活：active_camera_id 落盘 + GET 显示 online。"""
    h = _headers(client)
    cid = "snap_act_001"
    try:
        r = client.post("/api/v1/cameras", headers=h, json={
            "id": cid, "name": "激活快照", "source": "0",
        })
        assert r.status_code == 201, r.text
        r = client.put(f"/api/v1/cameras/{cid}/active", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["active_camera_id"] == cid
        # 配置文件：active 指针落盘
        assert _cfg_raw(client)["active_camera_id"] == cid
        # GET：状态可见为 online
        assert client.get(f"/api/v1/cameras/{cid}", headers=h).json()["status"] == "online"
        _assert_three_views_consistent(client, cid)
    finally:
        client.delete(f"/api/v1/cameras/{cid}", headers=h)


def test_config_persisted_after_mutation(client):
    """配置文件是唯一真值：改动后直接读盘可见（不依赖进程内存）。"""
    h = _headers(client)
    cid = "snap_persist_001"
    try:
        r = client.post("/api/v1/cameras", headers=h, json={
            "id": cid, "name": "落盘快照", "source": "rtsp://192.0.2.11:554/s",
            "username": "u", "password": "p",
        })
        assert r.status_code == 201, r.text
        client.put(f"/api/v1/cameras/{cid}", headers=h, json={"name": "落盘新名"})
        # 直接从磁盘读（每次重新 load，不缓存）
        cfg = _cfg_cam(client, cid)
        assert cfg["name"] == "落盘新名"
        assert "u:p@" in cfg["source"]
        # 内存视图 source 与磁盘一致（单一数据源成立的核心断言）
        assert client.app.state.cam.get(cid).source == cfg["source"]
    finally:
        client.delete(f"/api/v1/cameras/{cid}", headers=h)


@pytest.fixture
def seeded_cam(client):
    """预置一个带凭据的摄像头，测试后清理。"""
    h = _headers(client)
    cid = "snap_seed_001"
    r = client.post("/api/v1/cameras", headers=h, json={
        "id": cid, "name": "预置", "source": "rtsp://192.0.2.12:554/v",
        "username": "u", "password": "p",
    })
    assert r.status_code == 201, r.text
    yield cid
    client.delete(f"/api/v1/cameras/{cid}", headers=h)


def test_list_matches_config_ids(client, seeded_cam):
    """列表 id 集合 == 配置文件 id 集合 == 内部视图 id 集合。"""
    h = _headers(client)
    api_ids = {c["id"] for c in client.get("/api/v1/cameras", headers=h).json()}
    internal_ids = {c.id for c in client.app.state.cam.list()}
    config_ids = {c["id"] for c in _cfg_raw(client)["cameras"]}
    assert api_ids == internal_ids == config_ids, "三方摄像头清单漂移"
