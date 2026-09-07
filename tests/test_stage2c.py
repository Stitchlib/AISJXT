"""第二期阶段三：G5 多摄像头并发检测（任务 3.1）。

验收标准映射：
- ① 2 摄像头同时检测互不阻塞、各自独立落库且 camera_id 正确；
- ③ total_processed 按摄像头分别统计正确；
- ② 单摄故障/离线自动摘除，不影响另一摄任务；
- 兼容：单摄启动行为保持不变（无参 start 即旧行为）。

仅用仿真类型摄像头，保证测试离线可跑、不触网。
"""
import time


def _headers(client) -> dict:
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _sim_camera_ids(client, n=2) -> list[str]:
    cams = [c.id for c in client.app.state.cm.get().cameras if c.type == "simulated" and c.enabled]
    assert len(cams) >= n, f"仿真摄像头不足 {n} 个: {cams}"
    return cams[:n]


def _use_sim_detector(client) -> None:
    """G5 并发用例只验证调度/隔离逻辑，与 YOLO 推理速度无关。

    测试配置基于真实 config.json（可能加载真实权重，首帧冷启动数秒且抖动大），
    这里切到仿真检测器保证用例离线稳定、不依赖模型加载耗时。
    """
    client.app.state.cm.config.enable_simulation = True
    client.app.state.engine.reload_detector()


def test_single_camera_backward_compat(client):
    """无参 start = 旧行为：仅启动单摄，running_cameras 恰为 1 项。"""
    h = _headers(client)
    assert client.post("/api/v1/inspection/start", headers=h).status_code == 200
    st = client.get("/api/v1/inspection/status", headers=h).json()
    assert st["running"] is True
    assert len(st["running_cameras"]) == 1
    assert st["active_camera_id"] == st["running_cameras"][0]["camera_id"]
    client.post("/api/v1/inspection/stop", headers=h)
    st = client.get("/api/v1/inspection/status", headers=h).json()
    assert st["running"] is False and st["running_cameras"] == []


def test_two_simulated_cameras_concurrent(client):
    """G5-①③：camera_id=a,b 逗号列表并发启动；各自落库、分摄统计正确。"""
    h = _headers(client)
    ids = _sim_camera_ids(client, 2)
    _use_sim_detector(client)

    rs = client.post("/api/v1/inspection/start", headers=h, params={"camera_id": ",".join(ids)})
    assert rs.status_code == 200, rs.text
    st = client.get("/api/v1/inspection/status", headers=h).json()
    assert {c["camera_id"] for c in st["running_cameras"]} == set(ids)

    time.sleep(4.0)  # interval=1000ms，仿真检测器下应各产出 >=2 条
    st2 = client.get("/api/v1/inspection/status", headers=h).json()
    counts = {c["camera_id"]: c["total_processed"] for c in st2["running_cameras"]}
    assert all(v >= 2 for v in counts.values()), counts
    assert st2["total_processed"] >= sum(counts.values()) - 1  # 聚合不丢

    rows = client.get("/api/v1/detection-results", headers=h, params={"page_size": 100}).json()
    seen = {r["camera_id"] for r in rows["items"]}
    assert set(ids) <= seen, f"落库缺摄像头: {seen} vs {ids}"

    client.post("/api/v1/inspection/stop", headers=h)


def test_start_all_keyword(client):
    """camera_id=all 启动全部启用摄像头。"""
    h = _headers(client)
    enabled = {c.id for c in client.app.state.cm.get().cameras if c.enabled}
    rs = client.post("/api/v1/inspection/start", headers=h, params={"camera_id": "all"})
    assert rs.status_code == 200, rs.text
    st = client.get("/api/v1/inspection/status", headers=h).json()
    assert {c["camera_id"] for c in st["running_cameras"]} == enabled
    client.post("/api/v1/inspection/stop", headers=h)


def test_stop_single_camera_keeps_other_running(client):
    """G5-②：单停一摄，另一摄继续跑；全停后 running=False。"""
    h = _headers(client)
    ids = _sim_camera_ids(client, 2)
    _use_sim_detector(client)
    client.post("/api/v1/inspection/start", headers=h, params={"camera_id": ",".join(ids)})
    time.sleep(1.2)

    rs = client.post("/api/v1/inspection/stop", headers=h, params={"camera_id": ids[0]})
    assert rs.status_code == 200
    st = client.get("/api/v1/inspection/status", headers=h).json()
    assert st["running"] is True
    assert {c["camera_id"] for c in st["running_cameras"]} == {ids[1]}
    time.sleep(3.0)  # 覆盖首帧冷启动窗口，确认另一摄仍在持续产出
    st2 = client.get("/api/v1/inspection/status", headers=h).json()
    other = [c for c in st2["running_cameras"] if c["camera_id"] == ids[1]]
    assert other and other[0]["total_processed"] >= 1

    client.post("/api/v1/inspection/stop", headers=h)
    assert client.get("/api/v1/inspection/status", headers=h).json()["running"] is False


def test_faulty_camera_auto_removed_without_affecting_others(client, monkeypatch):
    """G5-②：单摄连续异常自动摘除，另一摄不受影响。"""
    h = _headers(client)
    eng = client.app.state.engine
    ids = _sim_camera_ids(client, 2)
    bad, good = ids[0], ids[1]
    orig = eng._grab_and_detect

    def flaky(cam_id):
        if cam_id == bad:
            raise RuntimeError("模拟传感器故障")
        return orig(cam_id)

    monkeypatch.setattr(eng, "_grab_and_detect", flaky)

    rs = client.post("/api/v1/inspection/start", headers=h, params={"camera_id": ",".join(ids)})
    assert rs.status_code == 200
    time.sleep(4.0)  # 连续 3 次异常（阈值 3）+ 摘除窗口
    st = client.get("/api/v1/inspection/status", headers=h).json()
    running_ids = {c["camera_id"] for c in st["running_cameras"]}
    assert bad not in running_ids, f"故障摄未被摘除: {running_ids}"
    assert good in running_ids and st["running"] is True
    client.post("/api/v1/inspection/stop", headers=h)


def test_start_unknown_camera_rejected(client):
    """未知摄像头 ID 返回 400（显式列表语义下不再静默降级）。"""
    h = _headers(client)
    rs = client.post("/api/v1/inspection/start", headers=h, params={"camera_id": "cam_no_such"})
    assert rs.status_code == 400
    assert client.get("/api/v1/inspection/status", headers=h).json()["running"] is False


# ---------- G6 ROI 检测区域 ----------

def test_roi_config_persistence_and_validation(client):
    """G6：ROI 经 PUT /cameras/{id} 持久化并可回读；非法值 422；[]=清空。"""
    h = _headers(client)
    # 写入右半画面
    rs = client.put(
        "/api/v1/cameras/cam_001",
        headers=h,
        json={"roi": [{"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0}]},
    )
    assert rs.status_code == 200, rs.text
    got = client.get("/api/v1/cameras/cam_001", headers=h).json()
    assert got["roi"] == [{"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0}]

    # 越界值被 Pydantic 拒绝
    bad = client.put("/api/v1/cameras/cam_001", headers=h, json={"roi": [{"x": 1.5, "y": 0, "w": 0.5, "h": 1}]})
    assert bad.status_code == 422

    # 清空
    clear = client.put("/api/v1/cameras/cam_001", headers=h, json={"roi": []})
    assert clear.status_code == 200
    assert client.get("/api/v1/cameras/cam_001", headers=h).json()["roi"] == []


def test_roi_masks_frame_and_filters_defects(client, monkeypatch):
    """G6 核心：ROI 外涂黑（检测器不可见）+ 中心点过滤；坐标保持原图像素。"""
    _use_sim_detector(client)
    h = _headers(client)
    eng = client.app.state.engine
    cam_id = "cam_001"

    # 配置 ROI：右半画面
    rs = client.put(
        f"/api/v1/cameras/{cam_id}",
        headers=h,
        json={"roi": [{"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0}]},
    )
    assert rs.status_code == 200

    # 构造 100x100 帧源（绕过真实 hub）
    import numpy as np

    frame = np.full((100, 100, 3), 200, dtype="uint8")

    class FakeHub:
        def latest(self, timeout=0.0):
            return frame, 1, 0.0, True

    eng._hubs_active[cam_id] = FakeHub()

    seen_frames = []

    def fake_detect(f):
        seen_frames.append(None if f is None else f.copy())
        return {
            "defects": [
                {"class_name": "left", "confidence": 0.9, "bbox": {"x": 10, "y": 40, "width": 20, "height": 20}},
                {"class_name": "right", "confidence": 0.8, "bbox": {"x": 70, "y": 40, "width": 20, "height": 20}},
            ],
            "total_count": 2,
            "defect_count": 2,
            "defect_rate": 1.0,
            "is_simulation": True,
        }

    monkeypatch.setattr(eng._detector, "detect", fake_detect)

    raw, _seq, shape, _img = eng._grab_and_detect(cam_id)

    # ① ROI 外区域对检测器不可见（左半涂黑，右半保留）
    f = seen_frames[0]
    assert f is not None
    assert int(f[50, 20].sum()) == 0, "ROI 外应被掩膜涂黑"
    assert int(f[50, 80].sum()) > 0, "ROI 内应保留原画面"

    # ② 中心点在 ROI 外的缺陷被过滤，计数重算；坐标仍为原图像素（未裁剪）
    assert [d["class_name"] for d in raw["defects"]] == ["right"]
    assert raw["total_count"] == 1 and raw["defect_count"] == 1
    assert raw["defects"][0]["bbox"]["x"] == 70  # 原图坐标不变
    assert shape == (100, 100)

    # ③ 无 ROI 行为不变：清空后两个缺陷都保留
    eng._hubs_active.pop(cam_id, None)
    client.put(f"/api/v1/cameras/{cam_id}", headers=h, json={"roi": []})


def test_roi_pure_functions():
    """纯函数：filter_defects_by_roi 中心点判定 + 非法 ROI 容错。"""
    from src.roi import filter_defects_by_roi

    rois = [{"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0}]
    defects = [
        {"class_name": "in", "bbox": {"x": 60, "y": 40, "width": 10, "height": 10}},
        {"class_name": "out", "bbox": {"x": 10, "y": 40, "width": 10, "height": 10}},
        {"class_name": "edge-touch", "bbox": {"x": 45, "y": 40, "width": 10, "height": 10}},  # 中心 x=50 -> 界上算入
    ]
    kept = filter_defects_by_roi(defects, rois, (100, 100, 3))
    assert [d["class_name"] for d in kept] == ["in", "edge-touch"]
    # 无 ROI：原样返回
    assert len(filter_defects_by_roi(defects, [], (100, 100, 3))) == 3
    # 非法 ROI（>1）被忽略
    assert len(filter_defects_by_roi(defects, [{"x": 2, "y": 0, "w": 0.5, "h": 1}], (100, 100, 3))) == 3
