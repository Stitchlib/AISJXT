from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import get_current_user
from ..models import InspectionStartResult, InspectionStatus, InspectionStopResult

router = APIRouter(prefix="/inspection", tags=["inspection"], dependencies=[Depends(get_current_user)])


@router.post("/start", response_model=InspectionStartResult)
async def start(
    camera_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    request: Request = None,
):
    """启动检测（第二期 G5）。

    - camera_id 缺省：旧行为，仅启动配置主摄；
    - camera_id="all"：启动全部启用摄像头；
    - camera_id="cam_a,cam_b"：并发启动指定列表（已运行的自动跳过，可运行中追加）。
    可选绑定生产批次（第二期 G4），绑定后该批次进行中记录自动继承。
    """
    if batch_id is not None:
        if not request.app.state.db.get_batch(batch_id):
            raise HTTPException(status_code=400, detail="批次不存在")
    try:
        await request.app.state.engine.start(camera_id, batch_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    eng = request.app.state.engine
    return {
        "status": "started",
        "active_camera_id": eng.active_camera_id,
        "active_batch_id": eng.active_batch_id,
        "running_cameras": eng.status()["running_cameras"],
    }


@router.post("/stop", response_model=InspectionStopResult)
async def stop(request: Request, camera_id: Optional[str] = None):
    """停止检测；camera_id 缺省全停（旧行为），指定则单停一摄（G5）。"""
    await request.app.state.engine.stop(camera_id)
    eng = request.app.state.engine
    return {
        "status": "stopped",
        "running": eng.status()["running"],
        "running_cameras": eng.status()["running_cameras"],
    }


@router.get("/status", response_model=InspectionStatus)
def status(request: Request):
    return InspectionStatus(**request.app.state.engine.status())
