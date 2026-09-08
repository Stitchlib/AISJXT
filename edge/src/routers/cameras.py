from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import get_current_user, require_role
from ..camera_capture import build_authed_source, probe_source
from ..config_manager import CameraConfig
from ..models import (
    MASK_MARK,
    ActiveCameraResult,
    CameraInfo,
    RoiRect,
    User,
    UserRole,
    infer_camera_type,
    mask_camera,
    normalize_camera_type,
)

router = APIRouter(prefix="/cameras", tags=["cameras"], dependencies=[Depends(get_current_user)])

# 权限矩阵（第三期 1.1/H2）：GET 只读保持登录即可；
# 增删改/active/discover/test → operator+；删除与凭据/来源修改 → admin。
_op_required = Depends(require_role(UserRole.OPERATOR))
_admin_required = Depends(require_role(UserRole.ADMIN))


class CameraCreate(BaseModel):
    id: str
    name: str
    # 允许 rtsp/http/usb/ip/network/simulated 及常见别名；空值则按 source 自动推断
    type: Optional[str] = None
    source: str = "0"
    enabled: bool = True
    username: Optional[str] = None
    password: Optional[str] = None
    roi: Optional[List[RoiRect]] = None  # G6：检测区域（归一化矩形列表）


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    status: Optional[str] = None
    type: Optional[str] = None
    source: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    # G6：检测区域；None=不修改，[]=清空（恢复全画面检测）
    roi: Optional[List[RoiRect]] = None


class CameraDiscover(BaseModel):
    subnet: str = "192.168.1"
    username: Optional[str] = None
    password: Optional[str] = None
    set_active: bool = True


class CameraTest(BaseModel):
    source: str
    username: Optional[str] = None
    password: Optional[str] = None


@router.get("", response_model=list[CameraInfo])
def list_cameras(request: Request):
    # H3：响应脱敏——内部清单保持原始 source 供取流，API 一律返回掩码值
    return [mask_camera(c) for c in request.app.state.cam.list()]


@router.get("/network/scan")
def scan_network(request: Request, subnet: str = "192.168.1"):
    """网络摄像头发现（轻量级端口探测，生产可替换为 ONVIF/RTSP）。"""
    return {"subnet": subnet, "found": request.app.state.cam.scan_network(subnet)}


@router.get("/{cam_id}", response_model=CameraInfo)
def get_camera(cam_id: str, request: Request):
    cam = request.app.state.cam.get(cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")
    return mask_camera(cam)


@router.post("", status_code=201, response_model=CameraInfo, dependencies=[_op_required])
def add_camera(body: CameraCreate, request: Request):
    """添加摄像头。

    类型处理：前端历史上会传 "rtsp"/"http"/"simulation" 等写法，与后端枚举不一致，
    过去会导致「选 RTSP 却永远不取真流」甚至写入配置后返回 500。现在统一归一化，
    未指定类型时按 source 自动推断（rtsp:// → rtsp，数字 → usb，http:// → http）。
    """
    cm = request.app.state.cm
    payload = body.model_dump()
    # G6：roi=None 表示"未提供"（用模型默认空列表）；显式传 None 会让
    # CameraInfo 的 List[RoiRect] 校验抛 ValidationError（ValueError 子类），
    # 被下方 except ValueError 捕获误报 409，故先剔除。
    if payload.get("roi") is None:
        payload.pop("roi", None)
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
    # 3.1 单一数据源：只写 ConfigManager，视图由 CameraManager 现场物化
    # H3：响应返回脱敏副本
    return mask_camera(request.app.state.cam.get(body.id))


@router.put("/{cam_id}", response_model=CameraInfo)
def update_camera(cam_id: str, body: CameraUpdate, request: Request, user: User = Depends(require_role(UserRole.OPERATOR))):
    # H3：前端会把"未修改"的 source 以脱敏值（user:***@host）回传，视为不修改，
    # 既防止掩码值写穿配置，也让"只想改名字"的请求不被误判为改凭据。
    if body.source is not None and MASK_MARK in body.source:
        body.source = None
    # 权限矩阵：source/凭据修改仅 admin（operator 改名称/启用/ROI 等仍可）
    if (body.source is not None or body.username is not None or body.password is not None) and user.role != UserRole.ADMIN:
        try:
            request.app.state.audit.record(
                actor=user.username, action="rbac_denied", target=f"/api/v1/cameras/{cam_id}",
                detail="修改摄像头来源/凭据需要 admin", ip=request.client.host if request.client else "",
            )
        except Exception:  # pragma: no cover - 审计失败不改变响应
            pass
        raise HTTPException(status_code=403, detail="修改摄像头来源或凭据需要管理员权限")
    cam = request.app.state.cam.get(cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")
    cm = request.app.state.cm
    # 3.1 单一数据源：只改配置条目并落盘，内存视图由 CameraManager 物化，不再双写
    updated = False
    for c in cm.get().cameras:
        if c.id != cam_id:
            continue
        updated = True
        if body.name is not None:
            c.name = body.name
        if body.enabled is not None:
            c.enabled = body.enabled
        if body.status is not None:
            c.status = body.status
        if body.type is not None:
            # 允许纠正历史脏类型（如把误设的 simulated 改回 rtsp 以真正取流）
            c.type = normalize_camera_type(body.type)
        if body.roi is not None:
            # G6：None=不修改，[]=清空恢复全画面
            c.roi = body.roi
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
                c.type = infer_camera_type(new_source)
    if updated:
        cm.save()
    # 来源/凭据/类型变了，旧的采集连接必须作废，下次观看重新按新配置开流
    hubs = getattr(request.app.state, "hubs", None)
    if hubs is not None:
        try:
            hubs.invalidate(cam_id)
        except Exception:
            pass
    # H3：响应返回脱敏副本（物化视图保持真实 source）
    return mask_camera(request.app.state.cam.get(cam_id))


@router.delete("/{cam_id}", dependencies=[_admin_required])
def delete_camera(cam_id: str, request: Request):
    cam = request.app.state.cam.get(cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")
    # 3.1 单一数据源：删除配置条目即完成（视图随配置派生），并联动清理 active 指针
    request.app.state.cm.remove_camera(cam_id)
    return {"ok": True, "removed": cam_id}


@router.post("/test", dependencies=[_op_required])
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


@router.post("/discover", dependencies=[_op_required])
def discover_cameras(body: CameraDiscover, request: Request, user: User = Depends(get_current_user)):
    """扫描网段并自动注册可用的网络摄像头（探测 RTSP 取流）。

    权限矩阵：发现本身 → operator+；携带凭据（写入新摄像头的账号密码）→ admin。
    """
    if (body.username or body.password) and user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="携带凭据的自动发现需要管理员权限")
    added = request.app.state.cam.discover_and_add(
        subnet=body.subnet,
        username=body.username,
        password=body.password,
        set_active=body.set_active,
    )
    # H3：响应脱敏（新注册摄像头的 source 含凭据）
    return {"added": [mask_camera(c).model_dump() for c in added], "count": len(added)}


@router.put("/{cam_id}/active", response_model=ActiveCameraResult, dependencies=[_op_required])
def set_active_camera(cam_id: str, request: Request):
    cam = request.app.state.cam.get(cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")
    try:
        request.app.state.cm.set_active_camera(cam_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # 3.1 单一数据源：状态写入配置（落盘），视图物化后 GET 可见 online
    request.app.state.cam.update_status(cam_id, "online")
    return {"ok": True, "active_camera_id": cam_id}
