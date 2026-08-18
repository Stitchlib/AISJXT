"""摄像头类型词表归一化 + 共享帧总线（frame_hub）回归测试。

这些测试守护两处真实修复：
- 类型词表前后端错位：前端给 rtsp/http/simulation，后端旧版只认 usb/ip/network，
  导致「选 RTSP 却永远不取真流」。normalize/infer/is_real 统一处理别名。
- 共享帧总线：一台摄像头只开一路采集，视频流与检测引擎共用同一路帧。
"""
import time

from fastapi.testclient import TestClient

from src.models import (
    CameraInfo,
    CameraType,
    infer_camera_type,
    is_real_camera_type,
    normalize_camera_type,
)
from src.frame_hub import HubRegistry


def test_normalize_camera_type_aliases():
    # 前端常见写法都应归一化到标准枚举值
    assert normalize_camera_type("RTSP") == CameraType.RTSP.value
    assert normalize_camera_type("rtsp") == CameraType.RTSP.value
    assert normalize_camera_type("onvif") == CameraType.RTSP.value
    assert normalize_camera_type("http") == CameraType.HTTP.value
    assert normalize_camera_type("https") == CameraType.HTTP.value
    assert normalize_camera_type("usb") == CameraType.USB.value
    assert normalize_camera_type("webcam") == CameraType.USB.value
    # 历史脏值 simulation -> simulated
    assert normalize_camera_type("simulation") == CameraType.SIMULATED.value
    assert normalize_camera_type("sim") == CameraType.SIMULATED.value
    # 空值 -> simulated（安全降级，不抛异常）
    assert normalize_camera_type(None) == CameraType.SIMULATED.value
    assert normalize_camera_type("") == CameraType.SIMULATED.value


def test_infer_camera_type_from_source():
    assert infer_camera_type("rtsp://192.168.1.4/stream1") == CameraType.RTSP.value
    assert infer_camera_type("rtsps://x") == CameraType.RTSP.value
    assert infer_camera_type("http://192.168.1.4/video") == CameraType.HTTP.value
    assert infer_camera_type("0") == CameraType.USB.value
    assert infer_camera_type("2") == CameraType.USB.value
    assert infer_camera_type("") == CameraType.SIMULATED.value


def test_is_real_camera_type():
    assert is_real_camera_type("rtsp") is True
    assert is_real_camera_type("http") is True
    assert is_real_camera_type("usb") is True
    assert is_real_camera_type("ip") is True
    assert is_real_camera_type("network") is True
    assert is_real_camera_type("simulated") is False
    assert is_real_camera_type("simulation") is False
    assert is_real_camera_type(None) is False


def _fake_cam(cid, ctype, source="", user="", pwd=""):
    return CameraInfo(
        id=cid, name=cid, type=CameraType(normalize_camera_type(ctype)),
        source=source, enabled=True, username=user, password=pwd,
    )


def test_hub_simulated_camera_produces_synthetic_frame():
    """仿真类型摄像头：hub 不应尝试打开真实设备，而直接产出合成帧（前端永不黑屏）。"""
    reg = HubRegistry(fps=15, linger=0.0)
    cam = _fake_cam("cam_sim", "simulation")
    hub = reg.acquire(cam)
    try:
        # 稍等采集线程跑出首帧
        frame, seq, _ts, is_real = hub.latest(timeout=3.0)
        assert frame is not None, "仿真摄像头必须产出合成帧"
        assert is_real is False, "合成帧不应标记为真实画面"
        assert seq >= 1
        assert reg.stats()[0]["source_kind"] == "synthetic"
    finally:
        reg.release(hub)


def test_hub_reference_counting_and_linger():
    """引用计数：多处观看共享同一路帧；归零后延迟释放（linger）。"""
    reg = HubRegistry(fps=15, linger=1.0)
    cam = _fake_cam("cam_ref", "simulation")
    h1 = reg.acquire(cam)
    h2 = reg.acquire(cam)
    assert h1 is h2, "同一摄像头应复用同一个 hub"
    assert h1._refs == 2
    reg.release(h1)
    assert h1._refs == 1
    reg.release(h2)
    # 归零后应安排延迟释放
    assert h1._release_at is not None
    # 重新 acquire 复用（尚未真正释放）
    h3 = reg.acquire(cam)
    assert h3 is h1
    reg.release(h3)
    reg.shutdown_all()


def test_hub_invalidates_on_config_change():
    """配置（来源/类型/凭据）变化时，旧采集连接应作废，下次按新配置重开。"""
    reg = HubRegistry(fps=15, linger=0.0)
    cam_a = _fake_cam("cam_cfg", "rtsp", source="rtsp://a/stream1")
    h = reg.acquire(cam_a)
    assert reg.peek("cam_cfg") is h
    # 来源变了 -> 作废
    reg.invalidate("cam_cfg")
    assert reg.peek("cam_cfg") is None
    # 下次 acquire 用新来源重建
    cam_b = _fake_cam("cam_cfg", "rtsp", source="rtsp://b/stream1")
    h2 = reg.acquire(cam_b)
    assert h2 is not h
    reg.release(h2)
    reg.shutdown_all()
