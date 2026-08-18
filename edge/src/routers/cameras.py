from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import get_current_user
from ..config_manager import CameraConfig
from ..models import CameraInfo, User

router = APIRouter(prefix="/cameras", tags=["cameras"], dependencies=[Depends(get_current_user)])


class CameraCreate(BaseModel):
    id: str
    name: str
    type: str = "simulated"
    source: str = "0"
    enabled: bool = True


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    status: Optional[str] = None


class CameraDiscover(BaseModel):
    subnet: str = "192.168.1"
    username: Optional[str] = None
    password: Optional[str] = None
    set_active: bool = True


@router.get("")
def list_cameras(request: Request):
    return request.app.state.cam.list()


@router.get("/network/scan")
def scan_network(request: Request, subnet: str = "192.168.1"):
    """网络摄像头发现（轻量级端口探测，生产可替换为 ONVIF/RTSP）。"""
    return {"subnet": subnet, "found": request.app.state.cam.scan_network(subnet)}


@router.get("/{cam_id}")
def get_camera(cam_id: str, request: Request):
    cam = request.app.state.cam.get(cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")
    return cam


@router.post("", status_code=201)
def add_camera(body: CameraCreate, request: Request):
    cm = request.app.state.cm
    try:
        cfg = CameraConfig(**body.model_dump())
        cm.add_camera(cfg)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    info = CameraInfo(**body.model_dump())
    request.app.state.cam.add(info)
    return request.app.state.cam.get(body.id)


@router.put("/{cam_id}")
def update_camera(cam_id: str, body: CameraUpdate, request: Request):
    cam = request.app.state.cam.get(cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")
    if body.name is not None:
        cam.name = body.name
    if body.enabled is not None:
        cam.enabled = body.enabled
    if body.status is not None:
        cam.status = body.status
    cm = request.app.state.cm
    for c in cm.get().cameras:
        if c.id == cam_id:
            if body.name is not None:
                c.name = body.name
            if body.enabled is not None:
                c.enabled = body.enabled
    cm.save()
    return cam


@router.delete("/{cam_id}")
def delete_camera(cam_id: str, request: Request):
    cam = request.app.state.cam.get(cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")
    request.app.state.cam.remove(cam_id)
    request.app.state.cm.remove_camera(cam_id)
    return {"ok": True, "removed": cam_id}


@router.post("/discover")
def discover_cameras(body: CameraDiscover, request: Request):
    """扫描网段并自动注册可用的网络摄像头（探测 RTSP 取流）。"""
    added = request.app.state.cam.discover_and_add(
        subnet=body.subnet,
        username=body.username,
        password=body.password,
        set_active=body.set_active,
    )
    return {"added": [c.model_dump() for c in added], "count": len(added)}


@router.put("/{cam_id}/active")
def set_active_camera(cam_id: str, request: Request):
    cam = request.app.state.cam.get(cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")
    try:
        request.app.state.cm.set_active_camera(cam_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    cam.status = "online"
    return {"ok": True, "active_camera_id": cam_id}
