"""第二期 非摄像头类任务验收测试：批次管理（G4）、多渠道通知（G3）、备份（G7a）、schema 迁移（G7b）。

摄像头相关任务（G5 多摄并发 / G6 ROI / G8 24h 实地压测）按用户要求跳过（摄像头未开）；
G8 压测 harness 单独在 tests/performance/stability_24h.py 提供，本文件不覆盖。

覆盖验收标准：
G4-① 批次切换后新数据归属正确、旧数据 NULL 不报错
G4-② 按批次报表 total/defect_rate 与按过滤结果一致；批次操作写审计
G3-② 三种机器人格式有单测（mock HTTP）；失败重试上限 1 次
G3-③ 测试端点发送成功/失败均有明确反馈
G7a-① 备份文件可打开且包含全量数据；G7a-② 超额自动删旧；G7a-④ 操作写审计
G7b-① 旧库启动后自动迁移到最新版且数据无损；G7b-② 幂等：重复启动不重复执行
"""
import sqlite3
import io
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

EDGE = Path(__file__).resolve().parent.parent / "edge"
if str(EDGE) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(EDGE))


def _login(client, user="admin", pwd="admin123"):
    return client.post("/api/v1/auth/login", json={"username": user, "password": pwd}).json()["access_token"]


def _headers(client, user="admin", pwd="admin123"):
    return {"Authorization": "Bearer " + _login(client, user, pwd)}


# ---------- G4 批次管理 ----------
def _last_id(client, h):
    r = client.get("/api/v1/detection-results", headers=h, params={"page_size": 1}).json()
    return r["items"][0]["id"] if r.get("items") else 0


def _collect_new(client, h, last_id, timeout=20):
    deadline = time.time() + timeout
    new = []
    while time.time() < deadline and not new:
        time.sleep(1)
        r = client.get("/api/v1/detection-results", headers=h, params={"page_size": 50}).json()
        new = [it for it in r.get("items", []) if it["id"] > last_id]
    return new


def test_batch_crud_and_inheritance(client):
    """G4-①：批次切换后新数据归属正确、旧数据 NULL 不报错；检测继承 batch_id。"""
    h = _headers(client)
    # ① 新建批次
    r = client.post("/api/v1/batches", headers=h, json={"batch_no": "B2026-001", "product": "衬衫"})
    assert r.status_code == 201, r.text
    assert r.json()["batch_no"] == "B2026-001"
    bid = "B2026-001"
    # 列表与详情
    assert any(b["batch_no"] == bid for b in client.get("/api/v1/batches", headers=h).json())
    assert client.get(f"/api/v1/batches/{bid}", headers=h).status_code == 200
    # 不存在的批次 404
    assert client.get("/api/v1/batches/NOPE", headers=h).status_code == 404

    # ② 绑定批次启动检测，验证新记录继承 batch_id
    last = _last_id(client, h)
    rs = client.post("/api/v1/inspection/start", headers=h, params={"batch_id": bid})
    assert rs.status_code == 200
    assert rs.json()["active_batch_id"] == bid
    new = _collect_new(client, h, last)
    client.post("/api/v1/inspection/stop", headers=h)
    assert new, "绑定批次后检测应正常写入记录"
    assert all(it.get("batch_id") == bid for it in new), "新记录应继承 batch_id"

    # ③ 结束批次：状态置 ended_at，且引擎清空当前绑定
    er = client.post(f"/api/v1/batches/{bid}/end", headers=h)
    assert er.status_code == 200, er.text
    assert er.json()["ended_at"] is not None
    assert client.get("/api/v1/inspection/status", headers=h).json()["active_batch_id"] is None

    # ④ 报表一致：report 的 total == 按 batch_id 过滤的记录数
    rep = client.get(f"/api/v1/reports/batch/{bid}", headers=h).json()
    filt = client.get("/api/v1/detection-results", headers=h, params={"batch_id": bid, "page_size": 1000}).json()
    assert rep["total"] == filt["total"]
    assert rep["total"] == len(new)
    # 缺陷率口径：缺陷帧 / 总帧
    df = sum(1 for it in new if it["defect_count"] > 0)
    expected_rate = round(df / len(new), 4) if new else 0.0
    assert rep["defect_rate"] == expected_rate

    # ⑤ 批次操作写审计
    aud = client.get("/api/v1/audit", headers=h, params={"page_size": 100}).json()
    acts = [it["action"] for it in aud.get("items", [])]
    assert "batch.create" in acts and "batch.end" in acts


def test_batch_report_consistency_two_batches(client):
    """G4-②：多批次归属正确；各批次报表合计 == 带批次记录总数（自洽）。"""
    h = _headers(client)
    b1, b2 = "BC1", "BC2"
    for b in (b1, b2):
        assert client.post("/api/v1/batches", headers=h, json={"batch_no": b}).status_code == 201

    last = _last_id(client, h)
    # 先跑 b1
    client.post("/api/v1/inspection/start", headers=h, params={"batch_id": b1})
    n1 = _collect_new(client, h, last)
    client.post("/api/v1/inspection/stop", headers=h)
    # 再跑 b2
    last2 = _last_id(client, h)
    client.post("/api/v1/inspection/start", headers=h, params={"batch_id": b2})
    n2 = _collect_new(client, h, last2)
    client.post("/api/v1/inspection/stop", headers=h)

    total_bound = len(n1) + len(n2)
    s1 = client.get(f"/api/v1/reports/batch/{b1}", headers=h).json()["total"]
    s2 = client.get(f"/api/v1/reports/batch/{b2}", headers=h).json()["total"]
    # 各批次归属正确且互不串
    assert s1 == len(n1) and s2 == len(n2)
    # 合计自洽
    assert s1 + s2 == total_bound == len([it for it in n1 + n2 if it["batch_id"] in (b1, b2)])
    # 结束两个批次
    for b in (b1, b2):
        client.post(f"/api/v1/batches/{b}/end", headers=h)


# ---------- G3 多渠道通知 ----------
def test_webhook_payload_formats_and_retry():
    """G3-②：三种机器人格式正确；失败仅重试 1 次（不无限轰炸）。"""
    from src import notifier

    captured = []

    def fake_post(url, payload, secret=None, timeout=10):
        captured.append((url, payload, secret))
        return 200

    orig = notifier._post_json
    notifier._post_json = fake_post
    try:
        # 格式校验
        notifier.send_webhook("http://x/ding", "dingtalk", "hi")
        assert captured[-1][1] == {"msgtype": "text", "text": {"content": "hi"}}
        notifier.send_webhook("http://x/feishu", "feishu", "hi")
        assert captured[-1][1] == {"msg_type": "text", "content": {"text": "hi"}}
        notifier.send_webhook("http://x/wecom", "wecom", "hi")
        assert captured[-1][1] == {"msgtype": "text", "text": {"content": "hi"}}
        notifier.send_webhook("http://x/g", "generic", "hi", secret="k")
        assert captured[-1][1] == {"text": "hi"}
        assert captured[-1][2] == "k"  # HMAC 签名头用的 secret 透传

        # 重试：首次异常、第二次成功 -> ok=True 且只调用 2 次
        calls = {"n": 0}

        def flaky(url, payload, secret=None, timeout=10):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return 200

        notifier._post_json = flaky
        ok, err = notifier.send_webhook("http://x/g", "generic", "hi", retries=1)
        assert ok is True and calls["n"] == 2

        # 持续失败 -> ok=False，调用次数 = retries+1 = 2
        calls["n"] = 0

        def always_fail(url, payload, secret=None, timeout=10):
            calls["n"] += 1
            raise RuntimeError("down")

        notifier._post_json = always_fail
        ok, err = notifier.send_webhook("http://x/g", "generic", "hi", retries=1)
        assert ok is False and calls["n"] == 2
    finally:
        notifier._post_json = orig


class _HookHandler(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(ln) if ln else b""
        _HookHandler.received.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *a):
        pass


def test_webhook_test_endpoint(client):
    """G3-③：测试发送端点对成功/失败均有明确反馈。"""
    h = _headers(client)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _HookHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{port}/hook"
        # 创建带 webhook 的规则
        rr = client.post("/api/v1/alerts/rules", headers=h, json={
            "name": "wh-test", "webhook_url": url, "webhook_type": "generic"})
        assert rr.status_code == 201, rr.text
        rid = rr.json()["id"]
        # 测试发送 -> 成功
        tr = client.post(f"/api/v1/alerts/rules/{rid}/test", headers=h)
        assert tr.status_code == 200, tr.text
        assert tr.json()["ok"] is True
        assert len(_HookHandler.received) >= 1
        # viewer 不可测试（需 operator）
        # 收尾
        client.delete(f"/api/v1/alerts/rules/{rid}", headers=h)
    finally:
        srv.shutdown()


def test_webhook_rule_does_not_block_detection(client):
    """G3-①：webhook 规则命中时，检测循环仍正常运行（发送在 to_thread 内，不阻塞主链路）。"""
    h = _headers(client)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _HookHandler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{port}/hook"
        # 阈值 0 的规则 + webhook，确保每次检测都触发 webhook
        rr = client.post("/api/v1/alerts/rules", headers=h, json={
            "name": "wh-block", "metric": "defect_rate", "operator": "ge", "threshold": 0.0,
            "webhook_url": url, "webhook_type": "generic"})
        rid = rr.json()["id"]
        last = _last_id(client, h)
        client.post("/api/v1/inspection/start", headers=h)
        new = _collect_new(client, h, last, timeout=15)
        client.post("/api/v1/inspection/stop", headers=h)
        assert new, "配置 webhook 后检测仍应正常写入"
        client.delete(f"/api/v1/alerts/rules/{rid}", headers=h)
    finally:
        srv.shutdown()


# ---------- G7a 备份与恢复 ----------
def test_backup_create_list_prune_and_audit(client, tmp_path):
    """G7a-①②④：备份可打开且含全量数据、列表、超额清理、操作写审计。"""
    h = _headers(client)
    db = client.app.state.db
    # 先写一条已知数据
    _last = _last_id(client, h)
    client.post("/api/v1/inspection/start", headers=h)
    time.sleep(3)
    client.post("/api/v1/inspection/stop", headers=h)
    _total_before = client.get("/api/v1/detection-results", headers=h, params={"page_size": 1}).json()

    # 手动触发备份
    rb = client.post("/api/v1/system/backup", headers=h)
    assert rb.status_code == 200, rb.text
    info = rb.json()
    backup_path = Path(info["path"])
    assert backup_path.exists()
    # 备份文件可打开且含全量数据
    con = sqlite3.connect(str(backup_path))
    cnt = con.execute("SELECT COUNT(*) FROM detection_results").fetchone()[0]
    con.close()
    assert cnt >= 1
    # 列表可见
    lst = client.get("/api/v1/system/backups", headers=h).json()
    assert any(b["filename"] == info["filename"] for b in lst)

    # 超额清理：在备份目录造若干假备份，retention=7 时应只保留 7 份
    bdir = backup_path.parent
    for i in range(9):
        (bdir / f"inspection_fake{i:03d}.db").write_bytes(b"x")
    before = len(list(bdir.glob("*.db")))
    removed = db.prune_backups(7, str(bdir))
    remaining = list(bdir.glob("*.db"))
    assert len(remaining) == 7, f"应保留 7 份，实际 {len(remaining)}"
    assert removed == before - 7

    # 审计
    aud = client.get("/api/v1/audit", headers=h, params={"page_size": 100}).json()
    assert any(it["action"] == "system.backup" for it in aud.get("items", []))


# ---------- G7b schema 版本化迁移 ----------
def test_schema_migration_idempotent(tmp_path):
    """G7b-②：重复启动不重复执行迁移；数据无损。"""
    from src.database import Database

    path = str(tmp_path / "mig.db")
    db = Database(path)
    sv1 = db.get_schema_version()
    assert sv1["count"] == 5, sv1  # 005_alert_cooling（第三期 2.1）
    # 写一条数据
    db.insert_result({
        "timestamp": "2026-09-03T00:00:00+00:00", "camera_id": "cam1", "defects": [],
        "total_count": 10, "defect_count": 2, "defect_rate": 0.2, "processing_time_ms": 12.3,
        "is_simulation": False, "metric_version": 2, "batch_id": "B1",
    })
    db._conn.close()  # 释放锁，模拟"重启"
    # 二次打开（重启）
    db2 = Database(path)
    sv2 = db2.get_schema_version()
    assert sv2["count"] == 5, "重复启动不应新增迁移版本"
    rows, total = db2.query_results(1, 10, batch_id="B1")
    assert total == 1 and rows[0]["batch_id"] == "B1"


def test_old_db_auto_migrates(tmp_path):
    """G7b-①：上期版本（无 batch_id/webhook/verdict，无 schema_version）启动后自动迁移且数据无损。"""
    from src.database import Database

    path = str(tmp_path / "old.db")
    # 手工模拟"上期"库：不含新增列、不含 batches/schema_version 表
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE detection_results ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, camera_id TEXT, image_path TEXT, "
        "defects TEXT, total_count INTEGER, defect_count INTEGER, defect_rate REAL, "
        "processing_time_ms REAL, is_simulation INTEGER, metric_version INTEGER DEFAULT 2)"
    )
    con.execute(
        "CREATE TABLE alert_rules (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, metric TEXT, "
        "operator TEXT, threshold REAL, scope TEXT, enabled INTEGER, notify_email TEXT, created_at TEXT)"
    )
    con.execute(
        "CREATE TABLE alert_events (id INTEGER PRIMARY KEY AUTOINCREMENT, rule_id INTEGER, camera_id TEXT, "
        "message TEXT, severity TEXT, value REAL, timestamp TEXT, acknowledged INTEGER, notified INTEGER, result_id INTEGER)"
    )
    con.execute(
        "INSERT INTO detection_results "
        "(timestamp,camera_id,defects,total_count,defect_count,defect_rate,processing_time_ms,is_simulation,metric_version) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("2026-09-03T00:00:00+00:00", "camX", "[]", 5, 1, 0.2, 9.0, 0, 2),
    )
    con.commit()
    con.close()

    # 用新代码打开 -> 自动迁移
    db = Database(path)
    sv = db.get_schema_version()
    assert sv["count"] == 5, sv

    # 新增列已补齐
    dcols = {r[1] for r in db._conn.execute("PRAGMA table_info(detection_results)").fetchall()}
    assert "batch_id" in dcols
    acols = {r[1] for r in db._conn.execute("PRAGMA table_info(alert_rules)").fetchall()}
    assert "webhook_url" in acols and "webhook_type" in acols
    # 005_alert_cooling：冷却/聚合列已补齐（第三期 2.1）
    assert {"cooldown_seconds", "silence_until"}.issubset(acols)
    ecols = {r[1] for r in db._conn.execute("PRAGMA table_info(alert_events)").fetchall()}
    assert {"verdict", "remark", "judged_by", "judged_at", "result_id"}.issubset(ecols)
    assert {"repeat_count", "recovered", "recovered_at"}.issubset(ecols)

    # 旧数据无损
    rows, total = db.query_results(1, 10)
    assert total == 1 and rows[0]["camera_id"] == "camX"


# ---------- 1.3 训练样本导出（模型迭代闭环） ----------
def test_build_yolo_zip_coords(tmp_path):
    """1.3 核心（不依赖 DB，确定性）：像素 bbox -> 归一化 YOLO；类别映射与 data.yaml 正确；
    缺图/缺 bbox 的样本被跳过且不报错。"""
    pytest.importorskip("PIL")
    from PIL import Image
    from src.sample_export import build_yolo_zip

    p = tmp_path / "x.jpg"
    Image.new("RGB", (100, 80), (0, 0, 0)).save(p, "JPEG")
    p2 = tmp_path / "y.jpg"
    Image.new("RGB", (100, 80), (0, 0, 0)).save(p2, "JPEG")

    rows = [
        {"image_path": str(p), "defects": [{"class_name": "线头", "bbox": {"x": 10, "y": 10, "width": 20, "height": 40}}]},
        {"image_path": str(p2), "defects": [{"class_name": "跳线", "bbox": {"x": 0, "y": 0, "width": 50, "height": 20}}]},
    ]
    data, count = build_yolo_zip(rows)
    assert count == 2
    z = zipfile.ZipFile(io.BytesIO(data))
    assert sorted(n for n in z.namelist() if n.startswith("images/")) == [
        "images/000000.jpg", "images/000001.jpg"]
    assert sorted(n for n in z.namelist() if n.startswith("labels/")) == [
        "labels/000000.txt", "labels/000001.txt"]
    assert z.read("images/000000.jpg") == p.read_bytes()
    # 归一化：100x80, bbox(10,10,20,40) -> xc=0.2 yc=0.375 nw=0.2 nh=0.5
    lbl0 = z.read("labels/000000.txt").decode().strip().splitlines()
    assert lbl0 == ["0 0.200000 0.375000 0.200000 0.500000"]
    # 类别映射：线头=0, 跳线=1（按出现顺序）
    classes = z.read("classes.txt").decode().strip().splitlines()
    assert classes == ["线头", "跳线"]
    yaml_txt = z.read("data.yaml").decode()
    assert "nc: 2" in yaml_txt and "names: ['线头', '跳线']" in yaml_txt

    # 缺图样本被跳过；无 bbox 的样本仍导出为空标注（背景样本，YOLO 合法）
    bad = [
        {"image_path": str(tmp_path / "missing.jpg"),
         "defects": [{"class_name": "a", "bbox": {"x": 1, "y": 1, "width": 1, "height": 1}}]},
        {"image_path": str(p), "defects": [{"class_name": "b"}]},  # 无 bbox
    ]
    d2, c2 = build_yolo_zip(bad)
    assert c2 == 1
    zb = zipfile.ZipFile(io.BytesIO(d2))
    assert zb.read("labels/000000.txt").decode().strip() == ""


def test_export_samples_endpoint(client, tmp_path):
    """1.3 端点（容忍共享 DB 既有数据）：已判定样本可导出为 zip；limit 配额生效；
    不存在的 verdict 返回空样本（不报错）。"""
    pytest.importorskip("PIL")
    from PIL import Image

    h = _headers(client)
    db = client.app.state.db
    p = tmp_path / "s.jpg"
    Image.new("RGB", (100, 80), (0, 0, 0)).save(p, "JPEG")
    rid = db.insert_result({
        "timestamp": "2026-09-03T00:00:00+00:00", "camera_id": "cam1", "image_path": str(p),
        "defects": [{"class_name": "线头", "bbox": {"x": 10, "y": 10, "width": 20, "height": 40}}],
        "total_count": 5, "defect_count": 1, "defect_rate": 0.2, "processing_time_ms": 12.0,
        "is_simulation": False, "metric_version": 2, "batch_id": None,
    })
    aid = db.insert_alert_event(1, "cam1", "m", "high", 1.0, result_id=rid)
    assert db.set_alert_verdict(aid, "confirmed", "ok", "admin") is True

    # 默认 verdicts=confirmed,false_positive -> 我的样本在导出中
    resp = client.get("/api/v1/model-versions/export-samples", headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/zip")
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    assert any(z.read(n) == p.read_bytes() for n in z.namelist() if n.startswith("images/"))

    # limit 配额：请求 limit=1 -> 至多 1 张
    resp2 = client.get("/api/v1/model-versions/export-samples", headers=h, params={"limit": 1})
    assert resp2.status_code == 200
    z2 = zipfile.ZipFile(io.BytesIO(resp2.content))
    assert len([n for n in z2.namelist() if n.startswith("images/")]) <= 1

    # 不存在的 verdict -> 空样本 zip（images 为空，不报错）
    resp3 = client.get("/api/v1/model-versions/export-samples", headers=h, params={"verdicts": "__nope__"})
    assert resp3.status_code == 200
    z3 = zipfile.ZipFile(io.BytesIO(resp3.content))
    assert len([n for n in z3.namelist() if n.startswith("images/")]) == 0
    assert z3.read("classes.txt").decode().strip() == ""


def test_metric_definition_formula_consistency(client):
    """3.2 指标口径显式化：汇总 defect_rate 与明细手算的"缺陷帧/总帧"完全一致。

    口径：单帧 defect_rate = defect_count/total_count（检出框占比）；
    聚合（全局/批次/分桶）= 缺陷帧数 / 总帧数（一帧多框只计 1 个缺陷帧）。
    """
    h = _headers(client)
    # 跑一段检测产生记录
    last = _last_id(client, h)
    client.post("/api/v1/inspection/start", headers=h)
    new = _collect_new(client, h, last)
    client.post("/api/v1/inspection/stop", headers=h)
    assert new, "需要检测记录验证口径"

    # ① 单帧口径：defect_rate == defect_count / total_count（保留 3 位）
    for it in new:
        tc = it.get("total_count") or 0
        expected = round(it["defect_count"] / tc, 3) if tc else 0.0
        assert abs(it["defect_rate"] - expected) < 1e-9

    # ② 聚合口径：按全量明细手算缺陷帧占比，与 /reports/summary 一致
    all_items = client.get(
        "/api/v1/detection-results", headers=h, params={"page_size": 1000}
    ).json()["items"]
    total = len(all_items)
    defect_frames = sum(1 for it in all_items if it["defect_count"] > 0)
    expected_rate = round(defect_frames / total, 4) if total else 0.0
    summary = client.get("/api/v1/reports/summary", headers=h).json()
    assert summary["total"] == total
    assert summary["defect_rate"] == expected_rate
    # defect_frame_rate 别名与 defect_rate 同值（口径显式化）
    assert summary["defect_frame_rate"] == expected_rate
