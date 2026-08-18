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
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from src.auth import AuthService
from src.camera_manager import CameraManager
from src.config_manager import ConfigManager
from src.database import Database
from src.inspection_engine import InspectionEngine
from src.routers import (
    alerts,
    auth,
    cameras,
    config,
    control,
    detection,
    health,
    model_versions,
    reports,
    system_health,
    users,
)
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
    engine = InspectionEngine(cm, db, ws, cam)
    auth_svc = AuthService(db, cm)
    # 注入到 app.state，供路由与 WebSocket 共享
    app.state.cm = cm
    app.state.db = db
    app.state.ws = ws
    app.state.cam = cam
    app.state.engine = engine
    app.state.auth = auth_svc
    logger.info(
        "系统初始化完成 | host=%s cameras=%d detector_mode=%s users=%d",
        cm.get().server_host,
        len(cam.list()),
        engine.detector_mode,
        db.count_users(),
    )
    # 可选：启动时自动扫描并注册同一局域网内的网络摄像头
    if cm.get().auto_discover:
        import socket
        import threading

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
    await engine.stop()


app = FastAPI(title="AI视觉质检系统", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


for r in (
    health.router,
    auth.router,
    cameras.router,
    config.router,
    detection.router,
    system_health.router,
    control.router,
    model_versions.router,
    reports.router,
    alerts.router,
    users.router,
):
    app.include_router(r, prefix="/api/v1")


@app.get("/")
def root():
    return {"service": "ai-visual-inspection", "version": "1.0.0", "docs": "/docs"}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await app.state.ws.connect(websocket)
    try:
        while True:
            try:
                msg = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            try:
                data = json.loads(msg)
                action = data.get("action")
                if action == "start":
                    await app.state.engine.start(data.get("camera_id"))
                    await websocket.send_json({"type": "control", "action": "start", "status": "ok"})
                elif action == "stop":
                    await app.state.engine.stop()
                    await websocket.send_json({"type": "control", "action": "stop", "status": "ok"})
            except Exception:
                pass
    finally:
        app.state.ws.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    cfg = ConfigManager().get()
    uvicorn.run(app, host=cfg.server_host, port=cfg.server_port)
