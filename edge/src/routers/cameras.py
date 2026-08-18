from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import get_current_user
from ..camera_capture import build_authed_source, probe_source
from ..config_manager import CameraConfig
from ..models import CameraInfo, CameraType, User, infer_camera_type, normalize_camera_type

router = APIRouter(prefix="/cameras", tags=["cameras"], dependencies=[Depends(get_current_user)])


class CameraCreate(BaseModel):
    id: str
    name: str
    # 允许 rtsp/http/usb/ip/network/simulated 及常见别名；空值则按 source 自动推断
    type: Optional[str] = None
    source: str = "0"
    enabled: bool = True
    username: Optional[str] = None
    password: Optional[str] = None


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    status: Optional[str] = None
    type: Optional[str] = None
    source: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class CameraDiscover(BaseModel):
    subnet: str = "192.168.1"
    username: Optional[str] = None
    password: Optional[str] = None
    set_active: bool = True


class CameraTest(BaseModel):
    source: str
    username: Optional[str] = None
    password: Optional[str] = None


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
    """添加摄像头。

    类型处理：前端历史上会传 "rtsp"/"http"/"simulation" 等写法，与后端枚举不一致，
    过去会导致「选 RTSP 却永远不取真流」甚至写入配置后返回 500。现在统一归一化，
    未指定类型时按 source 自动推断（rtsp:// → rtsp，数字 → usb，http:// → http）。
    """
    cm = request.app.state.cm
    payload = body.model_dump()
    ctype = normalize_camera_type(body.type) if body.type else infer_camera_type(body.source)
    payload["type"] = ctype
    try:
        cfg = CameraConfig(**payload)
        # 若提供了凭据且为 rtsp/http 源，将鉴权信息注入 source，确保取流可用
        if body.username and body.source.lower().startswith(("rtsp", "http")):
            cfg.source = build_authed_source(body.source, body.username, body.password)
        cm.add_camera(cfg)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    info = CameraInfo(**payload)
    info.source = cfg.source  # 响应需反映已注入的鉴权信息
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
    if body.type is not None:
        # 允许纠正历史脏类型（如把误设的 simulated 改回 rtsp 以真正取流）
        cam.type = CameraType(normalize_camera_type(body.type))
    cm = request.app.state.cm
    for c in cm.get().cameras:
        if c.id == cam_id:
            if body.name is not None:
                c.name = body.name
            if body.enabled is not None:
                c.enabled = body.enabled
            if body.type is not None:
                c.type = normalize_camera_type(body.type)
            # 凭据/来源更新：重新注入鉴权信息
            if body.source is not None or body.username is not None or body.password is not None:
                new_source = body.source if body.source is not None else c.source
                new_user = body.username if body.username is not None else c.username
                new_pass = body.password if body.password is not None else c.password
                if new_user and new_source.lower().startswith(("rtsp", "http")):
                    c.source = build_authed_source(new_source, new_user, new_pass)
                else:
                    c.source = new_source
                c.username = new_user
                c.password = new_pass
                # 未显式指定类型时，按新来源纠正类型，避免"改了 RTSP 地址仍按仿真处理"
                if body.type is None and body.source is not None:
                    inferred = infer_camera_type(new_source)
                    c.type = inferred
                    cam.type = CameraType(inferred)
                cam.source = c.source
    cm.save()
    # 来源/凭据/类型变了，旧的采集连接必须作废，下次观看重新按新配置开流
    hubs = getattr(request.app.state, "hubs", None)
    if hubs is not None:
        try:
            hubs.invalidate(cam_id)
        except Exception:
            pass
    return cam


@router.delete("/{cam_id}")
def delete_camera(cam_id: str, request: Request):
    cam = request.app.state.cam.get(cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")
    request.app.state.cam.remove(cam_id)
    request.app.state.cm.remove_camera(cam_id)
    return {"ok": True, "removed": cam_id}


@router.post("/test")
def test_camera_connection(body: CameraTest, request: Request):
    """探测给定来源（可带凭据）是否可连接并取到至少一帧。

    用于在添加/配置摄像头前验证账号密码（如 56789-abc）是否正确。
    """
    src = build_authed_source(body.source, body.username, body.password)
    try:
        ok = probe_source(src, timeout=8.0)
    except Exception as e:  # 任何异常都视为不可达，绝不抛出 500
        return {"ok": False, "message": f"探测异常：{e}"}
    return {"ok": ok, "message": "连接成功，可取流" if ok else "无法连接或取不到视频帧"}


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
