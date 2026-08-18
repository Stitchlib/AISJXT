"""编排层（模块协作中枢）。

inspection_engine 是模块间交互的总线：
  detector -> 产生结果 -> database(持久化) + websocket_manager(实时广播)
并对外暴露启停控制，供 API / WebSocket 指令驱动。

这样各模块保持单一职责，协作逻辑集中、可测试、易扩展。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .camera_manager import CameraManager
from .config_manager import ConfigManager
from .database import Database
from .detector import BaseDetector, build_detector
from .models import DetectionResult
from .notifier import process_alerts
from .websocket_manager import ConnectionManager

logger = logging.getLogger("inspection_engine")


class InspectionEngine:
    def __init__(
        self,
        config_mgr: ConfigManager,
        db: Database,
        ws: ConnectionManager,
        cam: CameraManager,
        hubs=None,
    ) -> None:
        self._cm = config_mgr
        self._db = db
        self._ws = ws
        self._cam = cam
        # 共享帧总线注册表（HubRegistry）。检测引擎不再自行打开摄像头，
        # 而是与视频流共用同一路帧——既避免设备抢占，也让检测框能叠到用户看到的那一帧上。
        self._hubs = hubs
        self._hub = None
        self._detector: BaseDetector = build_detector(self._cm.get())
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self.total_processed = 0
        self.last_result: Optional[DetectionResult] = None
        self.active_camera_id: Optional[str] = None

    @property
    def detector_mode(self) -> str:
        return "yolo" if not self._detector.is_simulation else "simulation"

    def reload_detector(self) -> None:
        """热更新检测器（模型版本激活/配置变更后调用）。"""
        self._detector = build_detector(self._cm.get())
        logger.info("检测器已热更新, mode=%s", self.detector_mode)

    async def start(self, camera_id: str | None = None) -> None:
        if self.running:
            return
        # 优先级：显式指定 > 配置 active_camera_id > 列表首个
        active = self._cm.get().active_camera_id
        candidate = (
            camera_id
            or (active if (active and self._cam.get(active)) else None)
            or (self._cam.list()[0].id if self._cam.list() else "cam_sim")
        )
        cam = candidate
        self.active_camera_id = cam
        # 向共享帧总线登记：真实摄像头由 hub 打开（仿真类型则 hub 出合成帧），
        # 无论哪种情况检测都能拿到帧，且与前端看到的画面是同一路。
        cam_obj = self._cam.get(cam)
        self._hub = None
        if cam_obj is not None and self._hubs is not None:
            try:
                self._hub = self._hubs.acquire(cam_obj)
            except Exception as e:
                logger.warning("帧总线获取失败，检测退化为无帧模式: %s", e)
                self._hub = None
        self.running = True
        self._task = asyncio.create_task(self._loop(cam))
        logger.info("检测任务启动, camera=%s, mode=%s", cam, self.detector_mode)

    async def stop(self) -> None:
        self.running = False
        if self._hub is not None:
            # 清掉标注，避免检测停了画面上还留着上一帧的缺陷框
            try:
                self._hub.clear_annotation()
            except Exception:
                pass
            try:
                if self._hubs is not None:
                    self._hubs.release(self._hub)
            except Exception:
                pass
            self._hub = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("检测任务已停止")

    def _grab_and_detect(self) -> tuple:
        """在工作线程中执行：从共享帧总线取最新帧 + 跑推理。

        放到线程里是因为 YOLO 推理是纯 CPU 阻塞调用，若在事件循环里直接跑，
        会连带卡住 WebSocket 广播与其它 HTTP 请求。
        返回 (raw结果, 帧序号, 帧尺寸(h,w))。
        """
        frame, seq, shape = None, 0, None
        if self._hub is not None:
            # 取"当前最新帧"即可，不要长时间阻塞等一帧新画面：检测引擎是采样，
            # 不是等流。否则首帧未到时会干等数秒，拖慢整条检测链路。
            frame, seq, _ts, _real = self._hub.latest(timeout=0.3)
            if frame is not None:
                shape = tuple(frame.shape[:2])
        raw = self._detector.detect(frame)
        return raw, seq, shape

    async def _loop(self, camera_id: str) -> None:
        while self.running:
            try:
                raw, frame_seq, frame_shape = await asyncio.to_thread(self._grab_and_detect)
                result = DetectionResult(
                    camera_id=camera_id,
                    defects=raw["defects"],
                    total_count=raw["total_count"],
                    defect_count=raw["defect_count"],
                    defect_rate=raw["defect_rate"],
                    processing_time_ms=raw["processing_time_ms"],
                    is_simulation=raw["is_simulation"],
                )
                rid = self._db.insert_result(result.to_db_row())
                result.id = rid
                self.last_result = result
                self.total_processed += 1
                # 把标注回写帧总线：视频流据此在画面上绘制缺陷框，
                # 这样用户看到的不只是"数字"，而是框在面料上的实际位置。
                if self._hub is not None:
                    try:
                        self._hub.set_annotation(
                            raw["defects"],
                            seq=frame_seq,
                            shape=frame_shape,
                            meta={
                                "detector_mode": self.detector_mode,
                                "defect_count": raw["defect_count"],
                            },
                        )
                    except Exception as e:  # 标注失败不影响检测主链路
                        logger.debug("标注回写失败: %s", e)
                await self._ws.broadcast({"type": "detection_result", "data": result.model_dump()})
                # 告警规则评估（落库 + 可选邮件），并实时广播
                try:
                    alert_ids = process_alerts(result, self._db, self._cm)
                    if alert_ids:
                        await self._ws.broadcast(
                            {"type": "alert", "data": {"ids": alert_ids, "camera_id": result.camera_id}}
                        )
                except Exception as e:  # 告警失败绝不影响主检测链路
                    logger.error("告警处理异常: %s", e)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # 单帧失败不应中断整个循环
                logger.error("检测循环异常: %s", e)
            await asyncio.sleep(1.0)

    def status(self) -> dict:
        return {
            "running": self.running,
            "total_processed": self.total_processed,
            "active_camera_id": self.active_camera_id,
            "last_result": self.last_result.model_dump() if self.last_result else None,
            "detector_mode": self.detector_mode,
        }
