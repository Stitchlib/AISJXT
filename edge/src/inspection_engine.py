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
from .models import CameraType, DetectionResult
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
    ) -> None:
        self._cm = config_mgr
        self._db = db
        self._ws = ws
        self._cam = cam
        self._detector: BaseDetector = build_detector(self._cm.get())
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self.total_processed = 0
        self.last_result: Optional[DetectionResult] = None
        self.active_camera_id: Optional[str] = None
        self._capture = None

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
        self._capture = None
        # 真实摄像头 + 真实模型：尝试打开帧源
        cam_obj = self._cam.get(cam)
        if (
            cam_obj
            and cam_obj.type in (CameraType.USB, CameraType.IP, CameraType.NETWORK)
            and not self._detector.is_simulation
        ):
            try:
                from .camera_capture import open_provider

                self._capture = open_provider(cam_obj.source)
                if self._capture is None:
                    logger.warning("摄像头 %s 无法打开，回退仿真", cam)
            except Exception as e:
                logger.warning("摄像头打开失败: %s", e)
                self._capture = None
        self.running = True
        self._task = asyncio.create_task(self._loop(cam))
        logger.info("检测任务启动, camera=%s, mode=%s", cam, self.detector_mode)

    async def stop(self) -> None:
        self.running = False
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception:
                pass
            self._capture = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("检测任务已停止")

    async def _loop(self, camera_id: str) -> None:
        while self.running:
            try:
                frame = None
                if self._capture is not None and not self._detector.is_simulation:
                    frame = self._capture.read()
                raw = self._detector.detect(frame)
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
