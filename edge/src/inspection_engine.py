"""编排层（模块协作中枢）。

inspection_engine 是模块间交互的总线：
  detector -> 产生结果 -> database(持久化) + websocket_manager(实时广播)
并对外暴露启停控制，供 API / WebSocket 指令驱动。

第二期 G5：从"单 active_camera 单任务"重构为任务字典
  {camera_id: asyncio.Task}：
- start 支持单个 / 逗号列表 / "all"；已运行时追加启动互不影响；
- stop 支持单停 / 全停；
- 共享 HubRegistry 帧总线 + 共享检测器实例（推理加锁串行，正确性优先）；
- 单摄连续异常自动摘除该摄任务，不影响其他摄像头；
- 单摄启动行为保持不变（无参 start 即旧行为，API 兼容）。

这样各模块保持单一职责，协作逻辑集中、可测试、易扩展。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .camera_manager import CameraManager
from .config_manager import ConfigManager
from .database import Database
from .detector import BaseDetector, build_detector
from .image_store import ImageStore
from .models import DetectionResult
from .notifier import process_alerts
from .roi import apply_roi_mask, filter_defects_by_roi
from .websocket_manager import ConnectionManager

logger = logging.getLogger("inspection_engine")

# 单摄连续异常阈值：超过即自动摘除该摄检测任务（G5 故障隔离）。
# 瞬时抖动（单次异常）不摘除；真实摄像头打不开走 hub 合成帧降级，不会走到这里。
MAX_CONSECUTIVE_ERRORS = 3


class InspectionEngine:
    def __init__(
        self,
        config_mgr: ConfigManager,
        db: Database,
        ws: ConnectionManager,
        cam: CameraManager,
        hubs=None,
        images: Optional[ImageStore] = None,
        bus=None,
    ) -> None:
        self._cm = config_mgr
        self._db = db
        self._ws = ws
        self._cam = cam
        # 通知总线（第三期 2.2）：告警评估只投递不等待，慢通知绝不拖慢检测节拍
        self._bus = bus
        # 共享帧总线注册表（HubRegistry）。检测引擎不再自行打开摄像头，
        # 而是与视频流共用同一路帧——既避免设备抢占，也让检测框能叠到用户看到的那一帧上。
        self._hubs = hubs
        self._detector: BaseDetector = build_detector(self._cm.get())
        # 缺陷图片留存（第二期 G1）：ImageStore 由 main 注入共享实例；未注入时按配置自行构建
        self._images: ImageStore = images or ImageStore.from_config(self._cm.get(), db)
        self.running = False
        # G5：每摄像头一个检测任务；hub/计数/连续异常均按摄像头维度维护
        self._tasks: Dict[str, asyncio.Task] = {}
        self._hubs_active: Dict[str, object] = {}
        self._proc_by_cam: Dict[str, int] = {}
        self._err_streak: Dict[str, int] = {}
        # 共享检测器串行推理锁：YOLO 推理是 CPU 阻塞调用，多摄并发下串行化保证正确性
        self._infer_lock = threading.Lock()
        self.total_processed = 0  # 进程级累计（跨多轮启停，不重置）
        # L5：本轮口径——每次"无任务→启动"归零；status 同时暴露本轮与累计两个口径
        self._run_processed = 0
        self._started_at: Optional[float] = None  # time.monotonic()，用于 since_start_seconds
        self._started_iso: Optional[str] = None   # UTC ISO，用于 started_at 展示
        self.last_result: Optional[DetectionResult] = None
        self.active_camera_id: Optional[str] = None
        # 当前绑定批次（第二期 G4）：检测启动时绑定，进行中自动继承，结束批次后清空
        self.active_batch_id: Optional[str] = None
        # L9 运行指标：最近推理延迟样本、帧丢弃计数、启动时刻
        self._latency_samples: deque = deque(maxlen=200)
        self._frame_drops: int = 0
        self._start_ts: float = time.time()

    @property
    def detector_mode(self) -> str:
        return "yolo" if not self._detector.is_simulation else "simulation"

    def reload_detector(self) -> None:
        """热更新检测器（模型版本激活/配置变更后调用）。"""
        self._detector = build_detector(self._cm.get())
        logger.info("检测器已热更新, mode=%s", self.detector_mode)

    # ---------- 摄像头目标解析（G5） ----------
    def _resolve_targets(self, camera_id: Optional[str]) -> List[str]:
        """把 start 的 camera_id 参数解析为目标摄像头列表。

        支持：None（旧行为：配置 active_camera_id > 列表首个）、
        "all"（全部启用摄像头）、逗号分隔列表（"cam_001,cam_002"）。
        显式列表中含未知 ID 时抛 ValueError（由路由转 400）。
        """
        cams = self._cam.list()
        by_id = {c.id for c in cams}
        if camera_id:
            s = str(camera_id).strip()
            if s.lower() == "all":
                ids = [c.id for c in cams if c.enabled]
                if not ids:
                    raise ValueError("没有已启用的摄像头")
                return ids
            ids = [p.strip() for p in s.split(",") if p.strip()]
            unknown = [i for i in ids if i not in by_id]
            if unknown:
                raise ValueError(f"未知摄像头: {', '.join(unknown)}")
            return ids
        # 旧行为：优先级 显式指定（上面已处理）> 配置 active_camera_id > 列表首个
        active = self._cm.get().active_camera_id
        if active and active in by_id:
            return [active]
        return [cams[0].id] if cams else ["cam_sim"]

    async def start(self, camera_id: str | None = None, batch_id: str | None = None) -> None:
        # 批次绑定（第二期 G4）：显式传入则接管；否则继承已绑定批次（进行中自动继承）
        if batch_id is not None:
            self.active_batch_id = batch_id
        targets = self._resolve_targets(camera_id)
        # 幂等：已在跑的摄像头跳过，仅启动新增目标（G5 支持运行中追加）
        new_targets = [t for t in targets if t not in self._tasks]
        if new_targets and not self._tasks:
            # L5：从空闲进入运行——本轮计时与计数重新开始（运行中追加不重置）
            self._started_at = time.monotonic()
            self._started_iso = datetime.now(timezone.utc).isoformat()
            self._run_processed = 0
        for cam in new_targets:
            # 向共享帧总线登记：真实摄像头由 hub 打开（仿真类型则 hub 出合成帧），
            # 无论哪种情况检测都能拿到帧，且与前端看到的画面是同一路。
            hub = None
            cam_obj = self._cam.get(cam)
            if cam_obj is not None and self._hubs is not None:
                try:
                    hub = self._hubs.acquire(cam_obj)
                except Exception as e:
                    logger.warning("帧总线获取失败(camera=%s)，检测退化为无帧模式: %s", cam, e)
                    hub = None
            self._hubs_active[cam] = hub
            self._proc_by_cam.setdefault(cam, 0)
            self._err_streak[cam] = 0
            self._tasks[cam] = asyncio.create_task(self._loop(cam))
            logger.info("检测任务启动, camera=%s, mode=%s", cam, self.detector_mode)
        if new_targets:
            self.active_camera_id = new_targets[0]
        self.running = bool(self._tasks)

    async def stop(self, camera_id: str | None = None) -> None:
        """停止检测：camera_id=None 全停（旧行为）；指定则单停一摄（G5）。"""
        targets = list(self._tasks.keys()) if camera_id is None else [camera_id]
        for cam in targets:
            task = self._tasks.pop(cam, None)
            hub = self._hubs_active.pop(cam, None)
            self._err_streak.pop(cam, None)
            if hub is not None:
                # 清掉标注，避免检测停了画面上还留着上一帧的缺陷框
                try:
                    hub.clear_annotation()
                except Exception:
                    pass
                try:
                    if self._hubs is not None:
                        self._hubs.release(hub)
                except Exception:
                    pass
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self._tasks.pop(cam, None)  # 摘除标记可能先于 cancel 生效，双保险
            logger.info("检测任务已停止, camera=%s", cam)
        self.running = bool(self._tasks)
        if not self._tasks:
            self._mark_idle()
            logger.info("全部检测任务已停止")

    def _detach_camera(self, camera_id: str, reason: str) -> None:
        """G5 故障隔离：摘除单摄任务（取消任务 + 释放 hub），不影响其他摄像头。"""
        task = self._tasks.pop(camera_id, None)
        hub = self._hubs_active.pop(camera_id, None)
        if hub is not None:
            try:
                hub.clear_annotation()
            except Exception:
                pass
            try:
                if self._hubs is not None:
                    self._hubs.release(hub)
            except Exception:
                pass
        if task and task is not asyncio.current_task():
            task.cancel()
        self.running = bool(self._tasks)
        if not self._tasks:
            self._mark_idle()
        logger.error("摄像头 %s 检测任务已自动摘除: %s", camera_id, reason)

    def _mark_idle(self) -> None:
        """运行态归零：清空本轮起始标记（累计 total_processed 保留）。"""
        self._started_at = None
        self._started_iso = None

    def camera_roi(self, camera_id: str) -> list:
        """读取摄像头 ROI 配置（G6）：归一化矩形列表，未配置返回空列表。"""
        try:
            for c in self._cm.get().cameras:
                if c.id == camera_id:
                    return list(getattr(c, "roi", None) or [])
        except Exception:
            pass
        return []

    def _grab_and_detect(self, camera_id: str) -> tuple:
        """在工作线程中执行：从共享帧总线取最新帧 + 跑推理 + 按模式保存现场图。

        放到线程里是因为 YOLO 推理是纯 CPU 阻塞调用，若在事件循环里直接跑，
        会连带卡住 WebSocket 广播与其它 HTTP 请求。
        图片落盘（编码 + 文件 IO）同样阻塞，一并放在线程里（第二期 G1）。
        返回 (raw结果, 帧序号, 帧尺寸(h,w), 现场图路径)。
        """
        hub = self._hubs_active.get(camera_id)
        frame, seq, shape = None, 0, None
        rois = self.camera_roi(camera_id)  # G6：检测区域（归一化）
        if hub is not None:
            # 取"当前最新帧"即可，不要长时间阻塞等一帧新画面：检测引擎是采样，
            # 不是等流。否则首帧未到时会干等数秒，拖慢整条检测链路。
            frame, seq, _ts, _real = hub.latest(timeout=0.3)
            if frame is not None:
                shape = tuple(frame.shape[:2])
        # G6：ROI 掩膜——并集之外区域涂黑，检测器天然忽略区域外目标
        if frame is not None and rois:
            frame = apply_roi_mask(frame, rois)
        # 共享检测器串行推理（G5）：多摄任务各自的工作线程会并发走到这里，
        # 加锁保证模型推理互斥（正确性优先；仿真检测器开销极小，串行无感）。
        with self._infer_lock:
            raw = self._detector.detect(frame)
        # G6：跨边界目标的二次过滤——bbox 中心不在 ROI 内的缺陷剔除，并重算计数
        if rois and raw.get("defects"):
            kept = filter_defects_by_roi(raw.get("defects"), rois, shape)
            n = len(kept)
            raw = {
                **raw,
                "defects": kept,
                "total_count": n,
                "defect_count": n,
                "defect_rate": round(n / n, 3) if n else 0.0,
            }
        if frame is None:
            self._frame_drops += 1
        # 缺陷图片留存（G1）：按 save_image_mode 决定是否把带标注帧落盘
        image_path = None
        try:
            mode = self._cm.get().save_image_mode
            if frame is not None and self._images.should_save(mode, raw.get("defect_count", 0)):
                image_path = self._images.save(frame, raw.get("defects"), camera_id=camera_id)
        except Exception as e:  # 保存失败绝不影响检测主链路
            logger.debug("现场图保存失败: %s", e)
            image_path = None
        return raw, seq, shape, image_path

    async def _loop(self, camera_id: str) -> None:
        while camera_id in self._tasks:
            try:
                raw, frame_seq, frame_shape, image_path = await asyncio.to_thread(
                    self._grab_and_detect, camera_id
                )
                result = DetectionResult(
                    camera_id=camera_id,
                    defects=raw["defects"],
                    total_count=raw["total_count"],
                    defect_count=raw["defect_count"],
                    defect_rate=raw["defect_rate"],
                    processing_time_ms=raw["processing_time_ms"],
                    is_simulation=raw["is_simulation"],
                    metric_version=raw.get("metric_version", 1 if raw["is_simulation"] else 2),
                    image_path=image_path,
                    batch_id=self.active_batch_id,
                )
                rid = self._db.insert_result(result.to_db_row())
                result.id = rid
                self.last_result = result
                self.total_processed += 1
                self._run_processed += 1
                self._proc_by_cam[camera_id] = self._proc_by_cam.get(camera_id, 0) + 1
                # 把标注回写帧总线：视频流据此在画面上绘制缺陷框，
                # 这样用户看到的不只是"数字"，而是框在面料上的实际位置。
                hub = self._hubs_active.get(camera_id)
                if hub is not None:
                    try:
                        hub.set_annotation(
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
                self._latency_samples.append(result.processing_time_ms)
                # 告警规则评估（落库 + 投递通知）。整个评估放入工作线程；
                # 通知发送经 NotificationBus 异步化（第三期 2.2）：
                # 有 bus 时仅入队（慢 webhook 不占线程），无 bus 时该线程内同步发送。
                try:
                    alert_ids = await asyncio.to_thread(
                        process_alerts, result, self._db, self._cm, self._bus
                    )
                    if alert_ids:
                        await self._ws.broadcast(
                            {"type": "alert", "data": {"ids": alert_ids, "camera_id": result.camera_id}}
                        )
                except Exception as e:  # 告警失败绝不影响主检测链路
                    logger.error("告警处理异常: %s", e)
                self._err_streak[camera_id] = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:  # 单帧失败不应中断整个循环
                self._err_streak[camera_id] = self._err_streak.get(camera_id, 0) + 1
                streak = self._err_streak[camera_id]
                logger.error("检测循环异常(camera=%s) 连续%d次: %s", camera_id, streak, e)
                if streak >= MAX_CONSECUTIVE_ERRORS:
                    # G5 故障隔离：该摄连续异常，自动摘除，不影响其他摄像头
                    self._detach_camera(camera_id, f"连续 {streak} 次检测异常")
                    return
            # 检测节拍由配置驱动（M14），不在代码里硬编码 sleep(1.0)。
            interval = max(0.0, self._cm.get().inspection_interval_ms / 1000.0)
            await asyncio.sleep(interval)

    def status(self) -> dict:
        # L5：started_at/since_start_seconds 描述本轮运行起点；
        # run_processed 为本轮帧数（空闲重启归零），total_processed 为进程累计（跨轮保留）。
        return {
            "running": bool(self._tasks),
            "total_processed": self.total_processed,
            "run_processed": self._run_processed,
            "started_at": self._started_iso,
            "since_start_seconds": (
                round(time.monotonic() - self._started_at, 1) if self._started_at is not None else None
            ),
            "active_camera_id": self.active_camera_id,
            "active_batch_id": self.active_batch_id,
            "running_cameras": [
                {"camera_id": cid, "total_processed": self._proc_by_cam.get(cid, 0)}
                for cid in self._tasks
            ],
            "last_result": self.last_result.model_dump() if self.last_result else None,
            "detector_mode": self.detector_mode,
        }

    # ---------- 批次绑定（第二期 G4） ----------
    def set_active_batch(self, batch_id: str) -> None:
        """绑定当前进行中批次（新产生的检测记录将继承该 batch_id）。"""
        self.active_batch_id = batch_id

    def clear_active_batch(self, batch_id: str | None = None) -> None:
        """结束批次后清空绑定；若指定 batch_id，则仅当当前绑定匹配时才清空（避免误清）。"""
        if batch_id is None or self.active_batch_id == batch_id:
            self.active_batch_id = None

    # ---------- L9 运行指标 ----------
    def cleanup_images(self) -> dict:
        """图片留存治理（第二期 G1）：保留期 + 配额双通道清理，供启动期与周期任务调用。"""
        cfg = self._cm.get()
        return self._images.cleanup(cfg.image_retention_days, cfg.image_quota_gb)

    def latency_stats(self) -> dict:
        samples = sorted(self._latency_samples)
        if not samples:
            return {"p50": None, "p95": None}
        n = len(samples)
        p50 = samples[n // 2]
        p95 = samples[min(n - 1, int(n * 0.95))]
        return {"p50": round(p50, 1), "p95": round(p95, 1)}

    def frame_drop_rate(self) -> float:
        total_frames = self.total_processed + self._frame_drops
        if total_frames == 0:
            return 0.0
        return round(self._frame_drops / total_frames, 4)

    def write_qps(self) -> float:
        elapsed = max(1.0, time.time() - self._start_ts)
        return round(self.total_processed / elapsed, 3)
