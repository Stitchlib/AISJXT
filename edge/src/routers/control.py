from typing import Optional

from fastapi import APIRouter, Depends, Request

from ..auth import get_current_user
from ..models import InspectionStatus, User

router = APIRouter(prefix="/inspection", tags=["inspection"], dependencies=[Depends(get_current_user)])


@router.post("/start")
async def start(camera_id: Optional[str] = None, request: Request = None):
    await request.app.state.engine.start(camera_id)
    return {"status": "started", "active_camera_id": request.app.state.engine.active_camera_id}


@router.post("/stop")
async def stop(request: Request):
    await request.app.state.engine.stop()
    return {"status": "stopped"}


@router.get("/status", response_model=InspectionStatus)
def status(request: Request):
    return InspectionStatus(**request.app.state.engine.status())
