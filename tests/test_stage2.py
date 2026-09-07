"""第二期阶段一验收测试：缺陷图片留存（G1）+ 告警人工判定（G2）。

覆盖验收标准：
G1-① 产生缺陷后磁盘存在图片且 DB image_path 非空、可经媒体端点访问
G1-② save_image_mode=none 时不落盘、无图路径为 NULL 不报错
G1-③ 配额触发清理且最旧图被删
G1-④ 路径穿越（../）与未登录访问返回 404/401
G2-① 三类判定可写可查且 judged_by 记录操作人
G2-② 误报率统计与手算一致
G2-③ viewer 判定被 403
G2-④ 判定操作写入审计日志
"""
import sys
import time
from pathlib import Path


EDGE = Path(__file__).resolve().parent.parent / "edge"
if str(EDGE) not in sys.path:
    sys.path.insert(0, str(EDGE))



def _login(client, user="admin", pwd="admin123"):
    return client.post("/api/v1/auth/login", json={"username": user, "password": pwd}).json()["access_token"]


def _headers(client, user="admin", pwd="admin123"):
    return {"Authorization": "Bearer " + _login(client, user, pwd)}


def _wait_for_image(client, h, timeout=25):
    """跑检测直到出现一条 image_path 非空且文件存在的记录，返回该记录。"""
    client.post("/api/v1/inspection/start", headers=h)
    deadline = time.time() + timeout
    found = None
    while time.time() < deadline and not found:
        time.sleep(1)
        r = client.get("/api/v1/detection-results", headers=h, params={"defect_only": "false", "page_size": 50})
        for it in r.json().get("items", []):
            if it.get("image_path"):
                found = it
                break
    client.post("/api/v1/inspection/stop", headers=h)
    return found


# ---------- G1：缺陷图片留存 ----------
def test_image_saved_and_accessible(client):
    """G1-①：检测产生图片（save_image_mode=all 强制全存），DB 回写路径，媒体端点可访问。"""
    h = _headers(client)
    # all 模式：无论有无缺陷都落盘，保证测试稳定
    assert client.put("/api/v1/config", headers=h, json={"save_image_mode": "all"}).status_code == 200
    try:
        item = _wait_for_image(client, h)
        assert item is not None, "检测运行后未产生任何带 image_path 的记录"
        p = Path(item["image_path"])
        assert p.exists() and p.suffix == ".jpg", f"磁盘上不存在现场图: {p}"
        # 媒体端点（Bearer）
        rel = p.as_posix()
        r = client.get(f"/api/v1/media/{rel}", headers=h)
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"
        assert r.content[:3] == b"\xff\xd8\xff"  # JPEG 魔术字节
    finally:
        client.put("/api/v1/config", headers=h, json={"save_image_mode": "defect_only"})


def test_media_ticket_and_auth(client):
    """G1-④：媒体端点 ticket 可用；未登录 401；路径穿越 404。"""
    h = _headers(client)
    assert client.put("/api/v1/config", headers=h, json={"save_image_mode": "all"}).status_code == 200
    try:
        item = _wait_for_image(client, h)
        assert item is not None
        rel = Path(item["image_path"]).as_posix()
        # 未登录 -> 401
        assert client.get(f"/api/v1/media/{rel}").status_code == 401
        # ticket（<img> 直连场景）
        tr = client.get("/api/v1/cameras/stream-ticket", headers=h)
        assert tr.status_code == 200
        ticket = tr.json()["ticket"]
        assert client.get(f"/api/v1/media/{rel}?ticket={ticket}").status_code == 200
        # 路径穿越 -> 404（统一 404 避免探测目录结构）
        assert client.get("/api/v1/media/../../etc/passwd", headers=h).status_code in (404, 400)
        assert client.get("/api/v1/media/..%2F..%2Fetc%2Fpasswd", headers=h).status_code in (404, 400)
        # 根目录外绝对路径 -> 404
        outside = Path("edge/main.py").resolve().as_posix()
        assert client.get(f"/api/v1/media/{outside}", headers=h).status_code == 404
        # 不存在的图 -> 404
        assert client.get("/api/v1/media/cam_x/20260101/000000_000.jpg", headers=h).status_code == 404
    finally:
        client.put("/api/v1/config", headers=h, json={"save_image_mode": "defect_only"})


def test_image_mode_none_disables_saving(client):
    """G1-②：save_image_mode=none 时不落盘，检测照常运行不报错。"""
    h = _headers(client)
    assert client.put("/api/v1/config", headers=h, json={"save_image_mode": "none"}).status_code == 200
    try:
        # 记下当前最大 id，只校验之后新产生的记录（避免误伤前序用例留下的带图记录）
        pre = client.get("/api/v1/detection-results", headers=h, params={"page_size": 1}).json()
        last_id = pre["items"][0]["id"] if pre.get("items") else 0
        client.post("/api/v1/inspection/start", headers=h)
        deadline = time.time() + 15
        new_items = []
        while time.time() < deadline and not new_items:
            time.sleep(1)
            r = client.get("/api/v1/detection-results", headers=h, params={"page_size": 30})
            new_items = [it for it in r.json().get("items", []) if it["id"] > last_id]
        client.post("/api/v1/inspection/stop", headers=h)
        assert new_items, "none 模式下检测应正常写入记录"
        assert all(it.get("image_path") is None for it in new_items), \
            "none 模式下新记录 image_path 应全为 NULL"
    finally:
        client.put("/api/v1/config", headers=h, json={"save_image_mode": "defect_only"})


def test_image_quota_cleanup(client):
    """G1-③：配额触发清理且最旧图片优先被删（直接调 ImageStore 单元逻辑）。"""
    from src.image_store import ImageStore

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        store = ImageStore(Path(td) / "images")
        # 造 3 张图：旧 -> 新
        files = []
        for i, age_days in enumerate((10, 5, 1)):
            day_dir = store.root / "cam" / f"2026010{i + 1}"
            day_dir.mkdir(parents=True, exist_ok=True)
            f = day_dir / f"img_{i}.jpg"
            f.write_bytes(b"\xff\xd8\xff" + b"x" * 4096)  # 4KB，确保超过测试配额（约1KB）
            old_ts = time.time() - age_days * 86400
            import os

            os.utime(f, (old_ts, old_ts))
            files.append(f)
        # 保留期 3 天：最旧两张（10 天、5 天）应被清掉，1 天的保留
        stat = store.cleanup(retention_days=3, quota_gb=10)
        assert stat["by_age"] == 2
        assert not files[0].exists() and not files[1].exists()
        assert files[2].exists()
        # 配额通道：保留期放宽，配额设 0.000001GB（约 1KB）迫使删最旧
        stat2 = store.cleanup(retention_days=0, quota_gb=0.000001)
        assert stat2["by_quota"] >= 1
        assert not any(f.exists() for f in files)


# ---------- G2：告警人工判定 ----------
def _create_viewer(client, h, username="v_stage2"):
    r = client.post("/api/v1/users", headers=h, json={
        "username": username, "password": "pw123456", "role": "viewer"})
    if r.status_code == 201:
        return r.json()["id"]
    # 已存在（重复跑）：找到它
    for u in client.get("/api/v1/users", headers=h).json():
        if u["username"] == username:
            return u["id"]
    return None


def _force_alert(client, h):
    """创建阈值 0 的规则并跑检测，返回（rule_id, event_id）。"""
    rr = client.post("/api/v1/alerts/rules", headers=h, json={
        "name": "stage2-强制告警", "metric": "defect_rate", "operator": "ge", "threshold": 0.0})
    rule_id = rr.json()["id"]
    client.post("/api/v1/inspection/start", headers=h)
    deadline = time.time() + 25
    event_id = None
    while time.time() < deadline and not event_id:
        time.sleep(1)
        ev = client.get("/api/v1/alerts/events", headers=h, params={"page_size": 50})
        for it in ev.json().get("items", []):
            if it.get("rule_id") == rule_id:
                event_id = it["id"]
                break
    client.post("/api/v1/inspection/stop", headers=h)
    return rule_id, event_id


def test_alert_verdict_flow_and_statistics(client):
    """G2-①②④：三类判定可写可查、统计一致、审计留痕。"""
    h = _headers(client)
    rule_id, e1 = _force_alert(client, h)
    assert e1 is not None, "未触发告警事件"
    _, e2 = _force_alert(client, h)
    _, e3 = _force_alert(client, h)
    assert e2 and e3
    try:
        # ① 三类判定：e1 误报、e2 确认、e3 漏报
        r1 = client.put(f"/api/v1/alerts/events/{e1}/verdict", headers=h,
                        json={"verdict": "false_positive", "remark": "背景干扰"})
        assert r1.status_code == 200
        assert r1.json()["verdict"] == "false_positive"
        assert r1.json()["judged_by"] == "admin"
        assert r1.json()["remark"] == "背景干扰"
        assert client.put(f"/api/v1/alerts/events/{e2}/verdict", headers=h,
                         json={"verdict": "confirmed"}).status_code == 200
        assert client.put(f"/api/v1/alerts/events/{e3}/verdict", headers=h,
                          json={"verdict": "missed"}).status_code == 200
        # 非法 verdict -> 400
        assert client.put(f"/api/v1/alerts/events/{e1}/verdict", headers=h,
                          json={"verdict": "bogus"}).status_code == 400
        # 不存在的事件 -> 404
        assert client.put("/api/v1/alerts/events/999999/verdict", headers=h,
                          json={"verdict": "confirmed"}).status_code == 404
        # ② 统计与手算一致（本测试窗口内至少 1 误报 1 确认 1 漏报）
        st = client.get("/api/v1/alerts/statistics", headers=h, params={"days": 1}).json()
        assert st["false_positive"] >= 1 and st["confirmed"] >= 1 and st["missed"] >= 1
        assert st["judged"] == st["confirmed"] + st["false_positive"] + st["missed"]
        assert st["total"] == st["judged"] + st["pending"]
        if st["judged"] > 0:
            fp_expect = round(st["false_positive"] / st["judged"], 4)
            assert st["false_positive_rate"] == fp_expect
        # ④ 审计留痕
        aud = client.get("/api/v1/audit", headers=h, params={"page_size": 100}).json()
        items = aud.get("items", aud) if isinstance(aud, dict) else aud
        acts = [it.get("action") for it in items]
        assert "alert.verdict" in acts
    finally:
        client.delete(f"/api/v1/alerts/rules/{rule_id}", headers=h)


def test_alert_verdict_viewer_forbidden(client):
    """G2-③：viewer 判定被 403。"""
    h = _headers(client)
    vid = _create_viewer(client, h)
    assert vid is not None
    vt = client.post("/api/v1/auth/login", json={"username": "v_stage2", "password": "pw123456"}).json()["access_token"]
    vh = {"Authorization": f"Bearer {vt}"}
    # viewer 读统计/事件列表可以（观察），但判定不行
    assert client.get("/api/v1/alerts/events", headers=vh).status_code == 200
    assert client.put("/api/v1/alerts/events/1/verdict", headers=vh,
                      json={"verdict": "confirmed"}).status_code == 403
    # 收尾：admin 删除测试 viewer
    client.delete(f"/api/v1/users/{vid}", headers=h)


def test_alert_event_links_result(client):
    """G2 联动：告警事件带 result_id，可反查检测记录（含 image_path 字段）。"""
    h = _headers(client)
    assert client.put("/api/v1/config", headers=h, json={"save_image_mode": "all"}).status_code == 200
    rule_id, eid = None, None
    try:
        rule_id, eid = _force_alert(client, h)
        assert eid is not None
        ev = client.get("/api/v1/alerts/events", headers=h, params={"page_size": 50}).json()
        target = next(it for it in ev["items"] if it["id"] == eid)
        rid = target.get("result_id")
        assert rid, "告警事件应回链检测记录 result_id"
        detail = client.get(f"/api/v1/detection-results/{rid}", headers=h)
        assert detail.status_code == 200
        assert "image_path" in detail.json()
        assert client.get("/api/v1/detection-results/99999999", headers=h).status_code == 404
    finally:
        client.put("/api/v1/config", headers=h, json={"save_image_mode": "defect_only"})
        if rule_id:
            client.delete(f"/api/v1/alerts/rules/{rule_id}", headers=h)
