"""共享帧总线：一台摄像头只开一路采集，帧同时供视频流与检测引擎使用。

本模块要解决三个真实存在的问题：

1. **设备抢占**。此前每个 `/video` 请求、以及检测引擎，各自 `cv2.VideoCapture` 打开
   同一台摄像头。USB 摄像头第二次打开必然失败；RTSP 则重复建流、浪费带宽（不少 IPC
   还有并发连接上限）。用户只要多开一个浏览器标签、或一边看实时页一边开预览弹窗，
   画面就可能挂掉。
2. **标注对不上帧**。检测引擎在自己那一路帧上算出 bbox，视频流是另一路帧，坐标无法
   叠加，前端只能看到"画面 + 一堆数字"，看不到缺陷框——对视觉质检系统这是核心缺失。
3. **多客户端重复解码**。N 个观看端等于 N 路解码，CPU 白烧。

做法：每个 camera_id 一个 `FrameHub`，后台单线程持续取帧并保存"最新帧 + 单调递增
序号"；消费方（视频流 / 检测引擎）按引用计数 attach/detach 共享同一路帧。检测引擎把
结果连同帧序号回写 hub，视频流据此在画面上绘制对应的缺陷框。引用归零后延迟 linger
秒才真正释放摄像头，避免前端刷新页面时反复开关设备。

可靠性：连续取帧失败会按退避策略自动重连（RTSP 抖动/断线自愈），重连期间自动降级为
合成画面，前端不会黑屏。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .models import is_real_camera_type

logger = logging.getLogger("frame_hub")

DEFAULT_FPS = 15
DEFAULT_LINGER = 6.0            # 引用归零后保持采集的秒数
ANNOTATION_TTL = 3.0            # 标注过期时间：超过则视为"检测已停"，不再画框
READ_FAIL_THRESHOLD = 15        # 连续取帧失败多少次触发重连
RECONNECT_BACKOFF = (1.0, 2.0, 5.0, 10.0, 15.0)


def _resolve_source(camera) -> Tuple[Any, bool]:
    """由摄像头对象推导实际采集源与"是否需要真实取流"。

    凭据（username/password）会注入 rtsp/http URL，因为 OpenCV 取流需要 URL 内嵌鉴权。
    """
    if not is_real_camera_type(getattr(camera, "type", None)):
        return None, False
    source = getattr(camera, "source", "") or ""
    user = getattr(camera, "username", "") or ""
    pwd = getattr(camera, "password", "") or ""
    if user:
        try:
            from .camera_capture import build_authed_source

            source = build_authed_source(str(source), user, pwd)
        except Exception as e:  # 注入失败不应阻断取流，退回原始 source
            logger.warning("凭据注入失败，使用原始来源: %s", e)
    return source, bool(str(source).strip())


class FrameHub:
    """单台摄像头的帧总线。线程安全。"""

    def __init__(
        self,
        camera_id: str,
        name: str,
        source: Any,
        want_real: bool,
        fps: int = DEFAULT_FPS,
        linger: float = DEFAULT_LINGER,
    ) -> None:
        self.camera_id = camera_id
        self.name = name or camera_id
        self.source = source
        self.want_real = want_real
        self.fps = max(1, min(int(fps), 30))
        self.linger = max(0.0, float(linger))

        self._lock = threading.RLock()
        self._frame = None
        self._seq = 0
        self._ts = 0.0
        self._real_frame = False          # 当前最新帧是否来自实体摄像头
        self._annotation: Optional[dict] = None
        self._refs = 0
        self._release_at: Optional[float] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._provider = None
        self._reconnects = 0
        self._read_failures = 0
        self._open_error: Optional[str] = None
        self._retired = False            # 配置变更后被作废，不再接受新的 attach

    # ---------------- 生命周期 ----------------

    def attach(self) -> "FrameHub":
        """登记一个消费者并确保采集线程在跑。必须与 detach 配对。"""
        with self._lock:
            self._refs += 1
            self._release_at = None
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(
                    target=self._run, name=f"framehub-{self.camera_id}", daemon=True
                )
                self._thread.start()
        return self

    def detach(self) -> None:
        """注销一个消费者；归零后延迟 linger 秒释放摄像头。"""
        with self._lock:
            self._refs = max(0, self._refs - 1)
            if self._refs == 0:
                self._release_at = time.time() + self.linger

    def shutdown(self) -> None:
        """立即停止采集（用于配置变更作废或应用退出）。"""
        with self._lock:
            self._retired = True
        self._stop.set()

    @property
    def retired(self) -> bool:
        with self._lock:
            return self._retired

    def _should_exit(self) -> bool:
        with self._lock:
            if self._retired:
                return True
            if self._refs > 0:
                return False
            if self._release_at is None:
                return True
            return time.time() >= self._release_at

    # ---------------- 采集线程 ----------------

    def _open_provider(self) -> None:
        if not self.want_real:
            return
        try:
            from .camera_capture import open_provider

            self._provider = open_provider(self.source)
            if self._provider is None:
                self._open_error = "无法打开摄像头（地址/凭据/网络不可达）"
                logger.warning("[%s] 打开摄像头失败，降级合成画面: %s", self.camera_id, self.source)
            else:
                self._open_error = None
                logger.info("[%s] 摄像头已打开", self.camera_id)
        except Exception as e:
            self._provider = None
            self._open_error = f"打开异常：{e}"
            logger.warning("[%s] 打开摄像头异常: %s", self.camera_id, e)

    def _close_provider(self) -> None:
        if self._provider is not None:
            try:
                self._provider.release()
            except Exception:
                pass
            self._provider = None

    def _reconnect(self) -> None:
        """连续取帧失败后按退避重连；重连期间前端看到的是合成画面而非黑屏。"""
        self._read_failures = 0
        self._reconnects += 1
        delay = RECONNECT_BACKOFF[min(self._reconnects - 1, len(RECONNECT_BACKOFF) - 1)]
        logger.warning(
            "[%s] 连续取帧失败，%.0fs 后重连（第 %d 次）", self.camera_id, delay, self._reconnects
        )
        self._close_provider()
        if self._stop.wait(delay):
            return
        self._open_provider()

    def _make_synthetic(self):
        try:
            from .video_stream import synthetic_frame

            return synthetic_frame(self.camera_id, self.name, time.time())
        except Exception as e:
            logger.error("[%s] 合成画面生成失败: %s", self.camera_id, e)
            return None

    def _run(self) -> None:
        interval = 1.0 / self.fps
        next_t = time.time()
        self._open_provider()
        try:
            while not self._stop.is_set():
                if self._should_exit():
                    break
                frame = None
                if self._provider is not None:
                    try:
                        frame = self._provider.read()
                    except Exception as e:
                        logger.warning("[%s] 取帧异常: %s", self.camera_id, e)
                        frame = None
                    if frame is None:
                        self._read_failures += 1
                        if self._read_failures >= READ_FAIL_THRESHOLD:
                            self._reconnect()
                    elif self._read_failures or self._reconnects:
                        self._read_failures = 0
                real = frame is not None
                if frame is None:
                    frame = self._make_synthetic()
                if frame is not None:
                    with self._lock:
                        self._frame = frame
                        self._seq += 1
                        self._ts = time.time()
                        self._real_frame = real
                next_t += interval
                sleep = next_t - time.time()
                if sleep > 0:
                    self._stop.wait(sleep)
                else:
                    next_t = time.time()  # 落后太多则重置节拍，避免追帧空转
        except Exception as e:  # pragma: no cover - 防御性收口
            logger.error("[%s] 采集线程异常终止: %s", self.camera_id, e)
        finally:
            self._close_provider()
            with self._lock:
                self._thread = None
                self._frame = None
            logger.info("[%s] 帧总线已停止", self.camera_id)

    # ---------------- 帧读取 ----------------

    def latest(self, timeout: float = 3.0) -> Tuple[Any, int, float, bool]:
        """返回 (frame, seq, ts, is_real)；等待首帧最多 timeout 秒，超时返回 (None, 0, 0.0, False)。

        返回的 frame 为共享引用，调用方需自行 copy 后再修改。
        """
        deadline = time.time() + max(0.0, timeout)
        while True:
            with self._lock:
                if self._frame is not None:
                    return self._frame, self._seq, self._ts, self._real_frame
                dead = self._thread is None and self._retired
            if dead or time.time() >= deadline:
                return None, 0, 0.0, False
            time.sleep(0.02)

    # ---------------- 检测标注 ----------------

    def set_annotation(
        self,
        defects: List[dict],
        seq: int = 0,
        shape: Optional[Tuple[int, int]] = None,
        meta: Optional[dict] = None,
    ) -> None:
        """由检测引擎回写本帧标注，供视频流叠加缺陷框。

        shape 为检测时所用帧的 (height, width)，视频流据此把坐标缩放到显示帧尺寸。
        """
        with self._lock:
            self._annotation = {
                "defects": list(defects or []),
                "seq": int(seq),
                "shape": shape,
                "ts": time.time(),
                "meta": dict(meta or {}),
            }

    def annotation(self, ttl: float = ANNOTATION_TTL) -> Optional[dict]:
        """取最近的标注；超过 ttl 秒视为检测已停，返回 None（画面不再显示过期框）。"""
        with self._lock:
            a = self._annotation
            if not a:
                return None
            if ttl and (time.time() - a["ts"]) > ttl:
                return None
            return a

    def clear_annotation(self) -> None:
        with self._lock:
            self._annotation = None

    # ---------------- 状态 ----------------

    def stats(self) -> dict:
        with self._lock:
            alive = self._thread is not None and self._thread.is_alive()
            return {
                "camera_id": self.camera_id,
                "name": self.name,
                "viewers": self._refs,
                "live": alive,
                "frames": self._seq,
                "fps_target": self.fps,
                "source_kind": "real" if self._real_frame else "synthetic",
                "want_real": self.want_real,
                "reconnects": self._reconnects,
                "open_error": self._open_error,
                "frame_age_ms": int((time.time() - self._ts) * 1000) if self._ts else None,
                "annotated": self._annotation is not None,
            }


class HubRegistry:
    """按 camera_id 管理 FrameHub 的注册表。挂在 app.state.hubs 上全局共享。"""

    def __init__(self, fps: int = DEFAULT_FPS, linger: float = DEFAULT_LINGER) -> None:
        self._hubs: Dict[str, FrameHub] = {}
        self._lock = threading.Lock()
        self.fps = fps
        self.linger = linger

    def acquire(self, camera) -> FrameHub:
        """取得（必要时创建）该摄像头的 hub 并 attach。调用方负责 release。

        若配置（来源/凭据/类型）已变化，作废旧 hub 并新建，确保按新配置取流。
        """
        source, want_real = _resolve_source(camera)
        cam_id = getattr(camera, "id", "unknown")
        with self._lock:
            hub = self._hubs.get(cam_id)
            if hub is not None and (
                hub.retired or hub.source != source or hub.want_real != want_real
            ):
                hub.shutdown()
                hub = None
            if hub is None:
                hub = FrameHub(
                    cam_id,
                    getattr(camera, "name", "") or cam_id,
                    source,
                    want_real,
                    self.fps,
                    self.linger,
                )
                self._hubs[cam_id] = hub
        return hub.attach()

    @staticmethod
    def release(hub: Optional[FrameHub]) -> None:
        if hub is not None:
            hub.detach()

    def peek(self, camera_id: str) -> Optional[FrameHub]:
        """不增加引用地查看 hub（用于状态查询 / 检测引擎回写标注）。"""
        with self._lock:
            return self._hubs.get(camera_id)

    def invalidate(self, camera_id: str) -> None:
        """配置变更后作废该摄像头的采集连接，下次观看时按新配置重开。"""
        with self._lock:
            hub = self._hubs.pop(camera_id, None)
        if hub is not None:
            hub.shutdown()
            logger.info("[%s] 配置变更，采集连接已作废", camera_id)

    def shutdown_all(self) -> None:
        with self._lock:
            hubs = list(self._hubs.values())
            self._hubs.clear()
        for h in hubs:
            h.shutdown()

    def stats(self) -> List[dict]:
        with self._lock:
            hubs = list(self._hubs.values())
        return [h.stats() for h in hubs]
