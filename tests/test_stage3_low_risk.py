"""第三期 3.5 低风险项验收：L3 RTSP 超时参数化 / L5 status 双口径 / L6 CORS 配置对齐。"""
import os
import time
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware

EDGE = Path(__file__).resolve().parent.parent / "edge"
if str(EDGE) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(EDGE))


def _headers(client, user="admin", pwd="admin123"):
    tok = client.post("/api/v1/auth/login", json={"username": user, "password": pwd}).json()["access_token"]
    return {"Authorization": "Bearer " + tok}


def _find_cors(app):
    stack = getattr(app, "middleware_stack", None)
    depth = 0
    while stack is not None and depth < 10:
        if isinstance(stack, CORSMiddleware):
            return stack
        stack = getattr(stack, "app", None)
        depth += 1
    return None


# ---------- L3：RTSP 超时参数化 ----------
def test_rtsp_timeout_configured_via_env(monkeypatch):
    from src.camera_capture import configure_ffmpeg_capture_options

    monkeypatch.delenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", raising=False)
    opts = configure_ffmpeg_capture_options(10)
    env = os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]
    assert env == opts
    # 10s = 10_000_000 微秒；TCP 传输与两类超时（新/旧 ffmpeg）都要带
    assert "rtsp_transport;tcp" in env
    assert "stimeout;10000000" in env
    assert "timeout;10000000" in env
    # 默认 30s
    assert "stimeout;30000000" in configure_ffmpeg_capture_options()
    # 非法/过小值被钳制为 >=1 微秒，不产生 0/负数
    assert "stimeout;1" in configure_ffmpeg_capture_options(0)


def test_rtsp_timeout_config_default_and_env_override(monkeypatch):
    from src.config_manager import AppConfig

    assert AppConfig().rtsp_open_timeout_sec == 30.0
    monkeypatch.setenv("AIQC_RTSP_OPEN_TIMEOUT_SEC", "12.5")
    # 重新构造一个独立 AppConfig 并应用环境覆盖逻辑
    from src.config_manager import ConfigManager

    cfg = AppConfig()
    ConfigManager._apply_env_overrides(cfg)
    assert cfg.rtsp_open_timeout_sec == 12.5
    # 非法值保持默认，不抛异常
    monkeypatch.setenv("AIQC_RTSP_OPEN_TIMEOUT_SEC", "not-a-number")
    cfg2 = AppConfig()
    ConfigManager._apply_env_overrides(cfg2)
    assert cfg2.rtsp_open_timeout_sec == 30.0


# ---------- L5：status 本轮/累计双口径 ----------
def test_inspection_status_since_start_and_run_counter(client):
    h = _headers(client)
    # 空闲态：无本轮起点
    st0 = client.get("/api/v1/inspection/status", headers=h).json()
    assert st0["running"] is False
    assert st0["started_at"] is None
    assert st0["since_start_seconds"] is None
    assert st0["run_processed"] == 0

    client.post("/api/v1/inspection/start", headers=h)
    try:
        # 等待至少产生一帧
        deadline = time.time() + 20
        st = {}
        while time.time() < deadline:
            st = client.get("/api/v1/inspection/status", headers=h).json()
            if st["run_processed"] > 0:
                break
            time.sleep(1)
        assert st["running"] is True
        assert st["started_at"] is not None
        assert st["since_start_seconds"] is not None and st["since_start_seconds"] >= 0
        assert st["run_processed"] > 0
        # 进程累计口径 >= 本轮（同进程内此前若跑过，只会更大）
        assert st["total_processed"] >= st["run_processed"]
        first_run = st["run_processed"]
        time.sleep(1.2)
        st2 = client.get("/api/v1/inspection/status", headers=h).json()
        assert st2["run_processed"] >= first_run
        # started_at 同一轮内保持不变
        assert st2["started_at"] == st["started_at"]
    finally:
        client.post("/api/v1/inspection/stop", headers=h)

    # 停止后：运行标记清空，累计值保留
    st3 = client.get("/api/v1/inspection/status", headers=h).json()
    assert st3["running"] is False
    assert st3["started_at"] is None
    assert st3["since_start_seconds"] is None
    assert st3["total_processed"] >= 1


def test_run_counter_resets_on_new_run(client):
    """第二轮启动后 run_processed 归零重计，total_processed 跨轮累计。"""
    h = _headers(client)

    def _run_once():
        client.post("/api/v1/inspection/start", headers=h)
        deadline = time.time() + 20
        st = {}
        while time.time() < deadline:
            st = client.get("/api/v1/inspection/status", headers=h).json()
            if st["run_processed"] >= 2:
                break
            time.sleep(1)
        run_n, cum = st["run_processed"], st["total_processed"]
        client.post("/api/v1/inspection/stop", headers=h)
        return run_n, cum

    r1, c1 = _run_once()
    r2, c2 = _run_once()
    assert r1 >= 2 and r2 >= 2
    # 第二轮本轮计数重新从 0 开始；累计单调不减且覆盖两轮
    assert c2 >= c1 + r2


# ---------- L6：CORS 与 lifespan 配置对齐 ----------
def test_cors_sync_with_lifespan_config(client):
    app = client.app
    cors = _find_cors(app)
    assert cors is not None, "中间件栈中应存在 CORSMiddleware"
    cm = app.state.cm
    original = list(cm.get().allowed_origins)
    try:
        # 精确来源白名单
        cm.get().allowed_origins = ["https://qa.example.com"]
        from main import _sync_cors

        _sync_cors(app)
        assert cors.allow_origins == ["https://qa.example.com"]
        assert cors.allow_all_origins is False
        assert cors.allow_methods == ["*"]
        # "*" 通配语义
        cm.get().allowed_origins = ["*"]
        _sync_cors(app)
        assert cors.allow_all_origins is True
        # 空列表：仅同源，不带任何跨域放行
        cm.get().allowed_origins = []
        _sync_cors(app)
        assert cors.allow_origins == []
        assert cors.allow_methods == []
        assert cors.allow_all_origins is False
    finally:
        cm.get().allowed_origins = original
        from main import _sync_cors

        _sync_cors(app)
