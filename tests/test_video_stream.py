"""视频流端点回归测试。

核心诉求：前端"看不到画面"的根因是系统从未把摄像头视频帧推给前端。
本文件锁定修复：GET /api/v1/cameras/{id}/video 必须返回 MJPEG 实时画面，
且需有效令牌（<img> 无法附带 Authorization 头，故支持 ?token=）。
"""
import sys
import time
from pathlib import Path

import pytest

EDGE = Path(__file__).resolve().parent.parent / "edge"
if str(EDGE) not in sys.path:
    sys.path.insert(0, str(EDGE))

import cv2  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
import src.video_stream as vs  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _login(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    return r.json()["access_token"]


def test_video_requires_token(client):
    # 无令牌 -> 401
    r = client.get("/api/v1/cameras/cam_001/video")
    assert r.status_code == 401


def test_video_wrong_token(client):
    r = client.get("/api/v1/cameras/cam_001/video?token=not-a-real-token")
    assert r.status_code == 401


def test_video_unknown_camera(client):
    tok = _login(client)
    r = client.get(f"/api/v1/cameras/does_not_exist/video?token={tok}")
    assert r.status_code == 404


def test_video_mjpeg_content(client, monkeypatch):
    tok = _login(client)

    # 只出一帧，避免无限 MJPEG 流让 TestClient 挂起
    def _one_frame(self, fps=15):
        frame = vs.synthetic_frame("cam_001", "主摄像头", time.time())
        ok, buf = cv2.imencode(".jpg", frame)
        assert ok
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"

    monkeypatch.setattr(vs.VideoStreamer, "stream", _one_frame)

    r = client.get(f"/api/v1/cameras/cam_001/video?token={tok}")
    assert r.status_code == 200
    assert "multipart/x-mixed-replace" in r.headers["content-type"]
    body = r.content
    assert body.startswith(b"--frame")
    # JPEG 魔术字节
    assert b"\xff\xd8\xff" in body
