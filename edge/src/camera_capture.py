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


def configure_ffmpeg_capture_options(open_timeout_sec: float = 30.0) -> str:
    """L3：参数化 RTSP 打开/读写超时，避免故障摄像头让取流线程长时间挂死。

    经 OpenCV 约定的 OPENCV_FFMPEG_CAPTURE_OPTIONS 环境变量下发（key;value 对以 |
    分隔），必须在首次 cv2.VideoCapture(rtsp://...) 之前调用（OpenCV/FFmpeg 在打开
    时一次性读取）：
    - rtsp_transport=tcp：弱网下避免 UDP 丢包导致的花屏与连接失败；
    - stimeout（微秒，RTSP 套接字 I/O 超时，旧版 ffmpeg 识别）；
    - timeout（微秒，新版 ffmpeg 协议打开超时）。
    返回实际写入的选项串，便于测试断言。
    """
    import os

    us = max(1, int(float(open_timeout_sec) * 1_000_000))
    opts = f"rtsp_transport;tcp|stimeout;{us}|timeout;{us}"
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = opts
    logger.info("FFmpeg 采集选项已设置（RTSP 超时 %ss）: %s", open_timeout_sec, opts)
    return opts


def build_authed_source(source: str, username: str | None, password: str | None) -> str:
    """为 rtsp/rtsps/http/https 类源注入或替换 user:pass@ 鉴权信息。

    - 无 username 时原样返回；
    - 已含 userinfo（host 前出现 @）则先去掉旧凭据再注入新凭据；
    - 其它协议（如纯数字 USB 索引）原样返回。
    """
    if not username or not source:
        return source
    low = source.lower()
    if not (low.startswith("rtsp") or low.startswith("http")):
        return source
    marker = "://"
    idx = source.find(marker)
    if idx == -1:
        return source
    head = source[: idx + len(marker)]
    rest = source[idx + len(marker):]
    # 去掉可能已存在的 userinfo（host 段里的 @）
    host_part = rest.split("/", 1)[0]
    if "@" in host_part:
        rest = rest.split("@", 1)[1]
    auth = f"{username}:{password or ''}@"
    return head + auth + rest


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
