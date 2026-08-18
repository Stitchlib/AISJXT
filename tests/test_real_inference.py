"""真实推理路径测试（仅在已安装 ultralytics 且存在有效权重时运行）。

属于"继续推进"中对仿真降级的实质性替换验证，确认：
- build_detector 在配置真实权重且关闭仿真时返回 YoloDetector（而非仿真降级）；
- YoloDetector 使用权重自带类别名（诚实标注，不再强制映射为服装瑕疵名）；
- detect(frame=None) 在无摄像头环境下也能跑通真实推理（合成帧兜底）。
"""
import sys
from pathlib import Path

import pytest

EDGE = Path(__file__).resolve().parent.parent / "edge"
if str(EDGE) not in sys.path:
    sys.path.insert(0, str(EDGE))

pytest.importorskip("ultralytics")  # 未安装 ultralytics 时整体跳过

from src.detector import YoloDetector, build_detector  # noqa: E402
from src.config_manager import AppConfig  # noqa: E402


def _find_weights() -> str | None:
    model_dir = EDGE / "model"
    if not model_dir.exists():
        return None
    # 选取目录下体积最大的有效权重；跳过过小的占位/损坏文件（如测试上传的 dummy）。
    pts = [p for p in model_dir.glob("*.pt") if p.stat().st_size > 1024 * 1024]
    if not pts:
        return None
    return str(max(pts, key=lambda p: p.stat().st_size))


WEIGHTS = _find_weights()
pytestmark = pytest.mark.skipif(WEIGHTS is None, reason="未找到有效模型权重（edge/model/*.pt）")


def test_build_detector_real_when_configured():
    cfg = AppConfig(model_path=WEIGHTS, enable_simulation=False)
    det = build_detector(cfg)
    assert not det.is_simulation
    assert isinstance(det, YoloDetector)


def test_yolo_detector_uses_model_names_and_runs():
    det = YoloDetector(WEIGHTS)
    assert not det.is_simulation
    # 诚实标注：类别名来自权重自带 names，而非强制服装映射
    assert isinstance(det.class_names, dict) and len(det.class_names) > 0
    res = det.detect()  # frame=None -> 合成帧兜底，无摄像头也能跑真实推理
    assert res["is_simulation"] is False
    assert "defects" in res and "processing_time_ms" in res
    for d in res["defects"]:
        assert isinstance(d["class_name"], str) and d["class_name"]
