"""视频帧流工具：为前端提供"看得到画面"的能力。

此前系统只把检测结果（缺陷数等）经 WebSocket 推给前端，摄像头帧图像被丢弃，
导致前端"实时画面"区域始终是空白——这是"看不到画面"的根本原因。

本模块补齐视频通道：
- 真实摄像头（USB/IP/RTSP/HTTP）：尝试用 OpenCV 打开并逐帧取流；
- 取流失败 / 仿真摄像头 / 无 OpenCV：自动生成"活的"合成画面（动态渐变 + 移动元素
  + 时间戳 + 摄像头名），保证前端永远能看到画面，便于在无实体摄像头环境下验证链路。

真实帧与合成帧都会叠加水印（名称、时间），方便现场核对。
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger("video_stream")

try:
    import cv2  # 惰性导入，缺失时仅能出合成画面
    import numpy as np

    _CV2 = True
except Exception:  # pragma: no cover - 环境无 cv2 时
    _CV2 = False
    cv2 = None
    np = None


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def synthetic_frame(camera_id: str, name: str, t: float) -> "np.ndarray":
    """生成一帧"活的"合成画面（动态），用于无实体摄像头时的占位/演示。

    返回 BGR numpy 数组，可直接 imencode 为 JPEG。
    """
    if not _CV2:
        raise RuntimeError("未安装 OpenCV，无法生成合成画面")
    h, w = 360, 640
    img = np.zeros((h, w, 3), dtype=np.uint8)
    # 动态渐变背景
    for y in range(h):
        c = int(28 + 26 * (y / h))
        img[y, :] = (c, c + 18, c + 38)
    # 移动的彩色光斑，制造"活"的观感
    cx = int(w * (0.5 + 0.40 * __import__("math").sin(t * 0.8)))
    cy = int(h * (0.5 + 0.30 * __import__("math").cos(t * 1.1)))
    cv2.circle(img, (cx, cy), 46, (78, 168, 255), -1)
    cv2.circle(img, (cx + 90, cy + 40), 26, (120, 220, 160), -1)
    # 文字水印
    cv2.putText(img, f"{name} ({camera_id})", (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(img, "仿真画面 · 未接入实体摄像头", (16, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 214, 120), 2)
    cv2.putText(img, _now_str(), (16, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 255, 200), 2)
    return img


def draw_overlay(frame: "np.ndarray", camera_id: str, name: str, t: float) -> "np.ndarray":
    """在真实帧上叠加水印（摄像头名称 + 时间）。返回新数组，不改原帧。"""
    if not _CV2:
        return frame
    img = frame.copy()
    h = img.shape[0]
    cv2.putText(img, f"{name} ({camera_id})", (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 120), 2)
    cv2.putText(img, _now_str(), (16, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 120), 2)
    return img


class VideoStreamer:
    """按请求拉起一路视频流：真实摄像头优先，失败自动降级合成画面。

    用法：作为 StreamingResponse 的生成器来源。客户端断开时自动释放采集资源。
    """

    def __init__(self, camera, provider) -> None:
        self.camera = camera
        self.provider = provider  # FrameProvider 或 None（仅合成）

    def stream(self, fps: int = 15):
        interval = 1.0 / max(1, min(int(fps), 30))
        last = 0.0
        try:
            while True:
                now = time.time()
                wait = interval - (now - last)
                if wait > 0.002:
                    time.sleep(wait)
                last = time.time()
                frame = None
                if self.provider is not None:
                    try:
                        frame = self.provider.read()
                    except Exception as e:  # 取帧异常 -> 降级合成
                        logger.warning("取帧失败，降级合成画面: %s", e)
                        frame = None
                if frame is None:
                    try:
                        frame = synthetic_frame(self.camera.id, self.camera.name or self.camera.id, time.time())
                    except Exception as e:
                        logger.error("合成画面生成失败: %s", e)
                        break
                else:
                    frame = draw_overlay(frame, self.camera.id, self.camera.name or self.camera.id, time.time())
                ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
                if not ok:
                    continue
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(buf)).encode()
                    + b"\r\n\r\n"
                    + buf.tobytes()
                    + b"\r\n"
                )
        except (GeneratorExit, StopIteration):
            pass
        except Exception as e:  # pragma: no cover - 防御性收口
            logger.error("视频流异常终止: %s", e)
        finally:
            if self.provider is not None:
                try:
                    self.provider.release()
                except Exception:
                    pass
