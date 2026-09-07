"""AI 视觉质检系统 - 边缘计算服务入口。

启动方式（项目根目录）：
    cd edge && python main.py
或（容器/生产）：
    uvicorn main:app --host 0.0.0.0 --port 8000

本文件只负责装配（依赖注入到 app.state）与生命周期管理，
具体业务逻辑分散在各 src 模块中，接口层只做协议转换。
"""
from __future__ import annotations

import json
import asyncio
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from src.audit import AuditLogger
from src.auth import AuthService
from src.camera_manager import CameraManager
from src.config_manager import ConfigManager
from src.database import Database
from src.frame_hub import HubRegistry
from src.image_store import ImageStore
from src.inspection_engine import InspectionEngine
from src.models import UserRole
from src.routers import (
    alerts,
    audit,
    auth,
    batches,
    cameras,
    config,
    control,
    detection,
    health,
    media,
    model_versions,
    reports,
    system,
    system_health,
    users,
    video,
)
from src.stream_tickets import WS_TICKET_TTL_SECONDS, consume_identity, issue as issue_ticket
from src.websocket_manager import ConnectionManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cm = ConfigManager()
    db = Database(cm.get().db_path)
    ws = ConnectionManager()
    cam = CameraManager()
    # 共享帧总线：一台摄像头只开一路采集，视频流与检测引擎共用同一路帧
    hubs = HubRegistry(fps=cm.get().stream_fps, linger=cm.get().stream_linger_seconds)
    # 缺陷图片留存（第二期 G1）：engine 与媒体端点共用同一个 ImageStore 实例
    images = ImageStore.from_config(cm.get(), db)
    engine = InspectionEngine(cm, db, ws, cam, hubs, images=images)
    auth_svc = AuthService(db, cm)

    # 后台预热检测器：首次 YOLO 推理有约数秒的 predictor 初始化开销，
    # 放到后台线程先跑一次，避免"第一次点开始检测"时整条链路卡 6 秒。
    def _warmup_detector() -> None:
        try:
            engine._detector.detect(None)
            logger.info("检测器预热完成, mode=%s", engine.detector_mode)
        except Exception as e:  # 预热失败绝不影响主服务
            logger.warning("检测器预热失败（不影响启动）：%s", e)

    if not engine._detector.is_simulation:
        threading.Thread(target=_warmup_detector, daemon=True).start()
    # 审计日志（L3）
    audit = AuditLogger(db)
    # 注入到 app.state，供路由与 WebSocket 共享
    app.state.cm = cm
    app.state.db = db
    app.state.ws = ws
    app.state.cam = cam
    app.state.hubs = hubs
    app.state.engine = engine
    app.state.images = images
    app.state.auth = auth_svc
    app.state.audit = audit
    logger.info(
        "系统初始化完成 | host=%s cameras=%d detector_mode=%s users=%d",
        cm.get().server_host,
        len(cam.list()),
        engine.detector_mode,
        db.count_users(),
    )
    # H5 安全自检：默认密钥/默认口令等隐患在启动日志中明确告警
    for w in cm.security_warnings():
        logger.warning("安全告警: %s", w)
    if cm.is_degraded():
        logger.error("配置降级启动: %s", cm.degraded_reason())
    # 启动时打印当前 schema 版本（第二期 G7b），便于排查迁移状态
    try:
        sv = db.get_schema_version()
        logger.info("数据库 schema 版本: %s（共 %d 个迁移）", sv.get("current"), sv.get("count"))
    except Exception:
        pass
    # 启动期治理（过期数据清理 + 图片留存治理 + 基线备份）改为**后台线程**执行：
    # 这三件事分别要跑 SQL 删除、遍历上万张图片、拷贝整库，同步跑在 lifespan 里会把
    # API 就绪时间从秒级拖到数分钟，且随数据积累越来越慢（24h 实跑实测：图片积累到
    # 1.5 万张后启动耗时约 6 分钟，直接导致压测脚本就绪等待超时）。
    # 它们都不是服务可用的前置条件，放到后台即可。
    app.state._startup_task = asyncio.create_task(
        asyncio.to_thread(_startup_housekeeping, db, cm, engine)
    )
    app.state._retention_task = asyncio.create_task(_retention_loop(db, cm, engine))
    app.state._backup_task = asyncio.create_task(_backup_loop(db, cm))
    # 可选：启动时自动扫描并注册同一局域网内的网络摄像头
    if cm.get().auto_discover:
        import socket

        def _autodiscover() -> None:
            try:
                ip = socket.gethostbyname(socket.gethostname())
                subnet = ".".join(ip.split(".")[:3])
            except Exception:
                subnet = "192.168.1"
            try:
                added = cam.discover_and_add(subnet=subnet, set_active=True)
                logger.info("启动自动发现：注册网络摄像头 %d 个", len(added))
            except Exception as e:
                logger.warning("启动自动发现失败（不影响主服务）：%s", e)

        threading.Thread(target=_autodiscover, daemon=True).start()
    yield
    # 启动期后台治理任务：不阻塞关停（线程内的清理会自行跑完）
    st = getattr(app.state, "_startup_task", None)
    if st is not None and not st.done():
        st.cancel()
    # 停止周期性清理任务
    rt = getattr(app.state, "_retention_task", None)
    if rt is not None:
        rt.cancel()
    bt = getattr(app.state, "_backup_task", None)
    if bt is not None:
        bt.cancel()
    await engine.stop()
    # 退出前必须释放所有摄像头，否则设备句柄/RTSP 连接会被残留占用
    hubs.shutdown_all()


def _guard_housekeeping(label: str, fn):
    """执行治理动作，吞掉一切异常——含 SystemExit / KeyboardInterrupt。

    为什么必须吞 SystemExit：治理动作跑在后台线程（asyncio.to_thread）里，
    任何逃逸到 asyncio Task 的 SystemExit 都会被 asyncio 默认异常处理器
    转成"停止整个事件循环"，等于一次清理失败就掀翻整台 API 服务。
    实测环境踩到过：清理删除文件被外部删除保护拦截抛 SystemExit → 服务进程直接消失。

    治理任务不是主链路，失败只能记录，绝不能影响服务可用性。
    """
    try:
        return fn()
    except BaseException as e:  # noqa: BLE001 - 有意吞掉全部异常，含 SystemExit
        logger.warning("%s 失败（已隔离，不影响服务）: %r", label, e)
        return None


def _startup_housekeeping(db, cm, engine) -> dict:
    """启动期治理：过期数据清理 + 图片留存治理 + 基线备份（同步阻塞，仅在后台线程调用）。"""
    out = {"rows_removed": 0, "removed_images": 0, "backup": None}
    out["rows_removed"] = _guard_housekeeping(
        "启动期数据清理", lambda: db.cleanup_retention(cm.get().data_retention_days)) or 0
    stat = _guard_housekeeping("启动期图片清理", lambda: engine.cleanup_images() or {})
    out["removed_images"] = (stat or {}).get("removed", 0)
    out["backup"] = _guard_housekeeping("启动期数据库备份", lambda: str(db.backup(cm.get().backup_dir)))
    _guard_housekeeping(
        "启动期旧备份清理",
        lambda: db.prune_backups(cm.get().backup_retention, cm.get().backup_dir),
    )
    logger.info("启动期治理完成（后台）: %s", out)
    return out


def _retention_work(db, cm, engine=None) -> dict:
    """清理主体：同步阻塞（SQL 删除 + 遍历上万图片文件），**必须在线程里跑**。

    第二期 24h 实跑教训：这段逻辑原先直接在事件循环上执行，遍历 1.5 万张图片的 I/O
    会把 uvicorn 的 event loop 卡住数十秒到数分钟，期间所有 HTTP 请求超时（实测
    17:31 那次清理导致 17:37 出现一次 HTTP 失联采样）。改由 asyncio.to_thread 承载后，
    清理再慢也不会影响 API 可用性。
    """
    days = cm.get().data_retention_days
    removed = _guard_housekeeping("周期性数据清理", lambda: db.cleanup_retention(days)) or 0
    stat = {}
    if engine is not None:
        stat = _guard_housekeeping("周期性图片清理", lambda: engine.cleanup_images() or {}) or {}
    return {"rows_removed": removed, "images": stat}


async def _retention_loop(db, cm, engine=None) -> None:
    """周期性清理过期检测数据（M3）与缺陷图片（第二期 G1）：默认每 6 小时一次。

    阻塞工作全部丢给线程执行，事件循环只负责等待，保证清理期间 API 仍然可用。
    """
    while True:
        try:
            await asyncio.sleep(6 * 3600)
            res = await asyncio.to_thread(_retention_work, db, cm, engine)
            if res["rows_removed"]:
                logger.info("周期性清理过期检测记录 %d 条（保留 %s 天）", res["rows_removed"], cm.get().data_retention_days)
            if (res["images"] or {}).get("removed"):
                logger.info(
                    "周期性清理缺陷图片 %d 张（保留期 %s / 配额 %sGB）",
                    res["images"]["removed"], cm.get().image_retention_days, cm.get().image_quota_gb,
                )
        except asyncio.CancelledError:
            break
        except Exception as e:  # pragma: no cover - 清理失败不致命
            logger.warning("周期性数据清理异常: %s", e)
        except BaseException as e:  # noqa: BLE001 - 连 SystemExit 也不能掀翻事件循环
            logger.warning("周期性数据清理被中断（已隔离）: %r", e)


def _backup_work(db, cm) -> dict:
    """备份主体：同步阻塞（sqlite backup 拷贝整库 + 清理旧备份），在线程里跑。"""
    cfg = cm.get()
    path = _guard_housekeeping("每日备份", lambda: str(db.backup(cfg.backup_dir)))
    removed = _guard_housekeeping(
        "旧备份清理", lambda: db.prune_backups(cfg.backup_retention, cfg.backup_dir)) or 0
    return {"path": path, "removed": removed}


async def _backup_loop(db, cm) -> None:
    """每日定时备份数据库（第二期 G7a）：默认每 24 小时一次，保留最近 N 份。"""
    while True:
        try:
            await asyncio.sleep(24 * 3600)
            res = await asyncio.to_thread(_backup_work, db, cm)
            logger.info("每日备份完成: %s（清理旧备份 %s 份）", res["path"], res["removed"])
        except asyncio.CancelledError:
            break
        except Exception as e:  # pragma: no cover - 备份失败不致命
            logger.warning("每日备份异常: %s", e)
        except BaseException as e:  # noqa: BLE001 - 连 SystemExit 也不能掀翻事件循环
            logger.warning("每日备份被中断（已隔离）: %r", e)


app = FastAPI(title="AI视觉质检系统", version="1.0.0", lifespan=lifespan)
# M8 CORS 收敛：默认仅同源（allow_origins 为空），生产经 AIQC_ALLOWED_ORIGINS 显式放行可信域。
_cors_origins = ConfigManager().get().allowed_origins or []
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"] if _cors_origins else [],
    allow_headers=["*"] if _cors_origins else [],
)


for r in (
    health.router,
    auth.router,
    # video.router 必须先于 cameras.router 注册：其 /cameras/stream-ticket 是单段路径，
    # 否则会被 cameras 的 GET /{cam_id} 抢先匹配（cam_id="stream-ticket"）导致换票 404。
    video.router,
    cameras.router,
    config.router,
    detection.router,
    system_health.router,
    system.router,
    control.router,
    media.router,
    model_versions.router,
    reports.router,
    batches.router,
    alerts.router,
    users.router,
    audit.router,
):
    app.include_router(r, prefix="/api/v1")


@app.get("/")
def root():
    return {"service": "ai-visual-inspection", "version": "1.0.0", "docs": "/docs"}


@app.post("/api/v1/ws-ticket")
def ws_ticket(request: Request):
    """签发 WS 握手一次性票据（第三期 1.3/M3）：30 秒有效、绑定当前用户身份。

    前端先 POST 换票，再以 /ws?ticket=<ticket> 连接；JWT 不再出现在 WS URL 与 access log。
    换票必须持 Bearer 令牌登录——WS 控制面要按角色鉴权，票据必须能绑定到用户身份。
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="换票需要登录（Bearer 令牌）")
    user = request.app.state.auth.get_current_user(request)
    ticket, ttl = issue_ticket(request, ttl=WS_TICKET_TTL_SECONDS, username=user.username)
    return {"ticket": ticket, "ttl": ttl}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    # H2：WebSocket 鉴权。支持三种握手方式（按优先级）：
    #   1) 连接 URL 携带 ?ticket=<一次性票据>（第三期 1.3：POST /api/v1/ws-ticket 换取，
    #      避免 JWT 进 access log；票据绑定用户身份，控制面仍按角色鉴权）；
    #   2) 连接 URL 携带 ?token=<jwt>（兼容保留）；
    #   3) 未带任何凭据时，等待首帧 {"action":"auth","token":"<jwt>"}（兜底，5 秒超时）。
    # 鉴权失败直接关闭连接（code 4401），避免未授权控制检测引擎或窃取数据。
    # 握手（accept）由 ConnectionManager.connect 统一完成，避免重复 accept。
    auth = app.state.auth
    await app.state.ws.connect(websocket)
    user = None
    ticket = websocket.query_params.get("ticket")
    if ticket:
        username = consume_identity(websocket, ticket)  # 注意：消费的是 websocket（同 app.state）
        if username:
            user = auth.get_user(username)
    token = websocket.query_params.get("token")
    if user is None and token:
        user = auth.get_user_from_token(token)
    # 若握手未携带有效凭据，则等待首帧 {"action":"auth","token":...} 完成鉴权；
    # 用超时兜底，避免「无令牌且不发帧」的空连接永久阻塞（H2 安全收口）。
    if user is None:
        try:
            first = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            data = json.loads(first)
            if data.get("action") == "auth":
                user = auth.get_user_from_token(data.get("token"))
        except Exception:
            user = None
    if user is None:
        try:
            await websocket.send_json({"type": "error", "code": 4401, "message": "未授权：缺少或无效的令牌"})
            await websocket.close(code=4401)
        finally:
            app.state.ws.disconnect(websocket)
        return

    try:
        while True:
            try:
                msg = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            try:
                data = json.loads(msg)
                action = data.get("action")
                if action in ("start", "stop"):
                    # 权限矩阵（第三期 1.1）：WS 控制面与 HTTP 一致 → operator+（原 admin-only 放宽）
                    if user.role not in (UserRole.ADMIN, UserRole.OPERATOR):
                        try:
                            app.state.audit.record(
                                actor=user.username, action="rbac_denied", target="/ws",
                                detail=f"WS 启停被拒 role={user.role.value}",
                                ip=websocket.client.host if websocket.client else "",
                            )
                        except Exception:  # pragma: no cover - 审计失败不改变响应
                            pass
                        await websocket.send_json(
                            {"type": "error", "code": 4403, "message": "权限不足：需要操作员及以上权限"}
                        )
                        continue
                    if action == "start":
                        await app.state.engine.start(data.get("camera_id"), data.get("batch_id"))
                        await websocket.send_json({"type": "control", "action": "start", "status": "ok"})
                    else:
                        await app.state.engine.stop()
                        await websocket.send_json({"type": "control", "action": "stop", "status": "ok"})
                else:
                    await websocket.send_json(
                        {"type": "error", "code": 4400, "message": f"未知指令: {action}"}
                    )
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "code": 4400, "message": "消息格式错误"})
            except Exception as e:
                # H2：指令异常不再静默吞掉，记录日志并回错误帧，便于排查
                logger.error("WS 指令处理异常: %s", e)
                await websocket.send_json({"type": "error", "code": 4500, "message": "服务器内部错误"})
    finally:
        app.state.ws.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    cfg = ConfigManager().get()
    uvicorn.run(app, host=cfg.server_host, port=cfg.server_port)
