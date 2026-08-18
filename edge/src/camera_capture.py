"""真实摄像头帧源：OpenCV 惰性导入，USB / IP / RTSP 通用。

设计原则：
- 仅在"真实摄像头类型 + cv2 可用 + 真实检测模型"三者同时满足时启用；
  否则引擎使用仿真路径。
- 任何失败都安全降级（返回 None），绝不让采集异常中断检测主链路。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("camera_capture")


class FrameProvider:
    def __init__(self, source) -> None:
        self._cap = None
        try:
            import cv2  # 惰性导入，无 cv2 环境不阻塞

            self._cap = cv2.VideoCapture(int(source) if str(source).isdigit() else str(source))
            if not self._cap.isOpened():
                logger.warning("无法打开摄像头源: %s", source)
                self._cap = None
        except Exception as e:
            logger.warning("摄像头初始化失败（将使用仿真）: %s", e)
            self._cap = None

    @property
    def available(self) -> bool:
        return self._cap is not None

    def read(self):
        if self._cap is None:
            return None
        try:
            ok, frame = self._cap.read()
            return frame if ok else None
        except Exception:
            return None

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None


def open_provider(source) -> Optional[FrameProvider]:
    """打开帧源；不可用时返回 None（交由引擎降级仿真）。"""
    p = FrameProvider(source)
    return p if p.available else None


def probe_source(source: str, timeout: float = 5.0) -> bool:
    """探测给定源是否可打开并取到至少一帧（用于网络摄像头自动发现）。

    返回 True 表示可用；任何异常 / 超时 / 取不到帧均返回 False。
    探测在守护线程中进行，避免 RTSP 握手卡死阻塞调用方。
    """
    import threading

    state: dict = {"ok": False, "cap": None}

    def _try() -> None:
        try:
            import cv2

            cap = cv2.VideoCapture(str(source))
            state["cap"] = cap
            if not cap.isOpened():
                return
            ok, frame = cap.read()
            state["ok"] = bool(ok and frame is not None)
        except Exception:
            state["ok"] = False
        finally:
            try:
                if state["cap"] is not None:
                    state["cap"].release()
            except Exception:
                pass

    t = threading.Thread(target=_try, daemon=True)
    t.start()
    t.join(timeout)
    return state["ok"]
