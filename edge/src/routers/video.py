"""视频流接口：把摄像头画面（含缺陷标注）以 MJPEG 推给前端。

端点：
- GET /cameras/{cam_id}/video     -> multipart/x-mixed-replace MJPEG 实时画面（已配置摄像头）
- GET /cameras/{cam_id}/snapshot  -> 单帧 JPEG（缩略图 / 报告插图 / 快速自检）
- GET /cameras/preview/stream    -> 免落库的临时预览（添加/配置摄像头前先验证来源是否可取流）
- GET /cameras/streams/status     -> 各路采集的观看数与健康状态（排障用）

鉴权：MJPEG 经 <img src> 拉取，无法附带 Authorization 头，故支持 ?token= 查询参数；
也兼容标准 Authorization: Bearer 头。无效则 401。token 即登录后前端持有的 JWT。

采集共享：所有观看端共用 app.state.hubs 里的同一路 FrameHub，避免多开标签页时
重复打开同一台摄像头（USB 会直接失败、RTSP 会浪费带宽甚至超出设备连接数上限）。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from ..models import CameraInfo, CameraType, infer_camera_type, normalize_camera_type
from ..video_stream import VideoStreamer, encode_jpeg, render_frame

logger = logging.getLogger("video_router")

router = APIRouter(prefix="/cameras", tags=["video"])


def _authenticate_video(request: Request):
    """视频流鉴权：优先 ?token=，回退 Authorization 头。"""
    tok = request.query_params.get("token")
    if not tok:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            tok = header[len("Bearer "):]
    user = request.app.state.auth.get_user_from_token(tok) if tok else None
    if user is None:
        raise HTTPException(status_code=401, detail="未授权：视频流需要有效令牌")
    return user


def _require_camera(request: Request, cam_id: str):
    cam = request.app.state.cam.get(cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="摄像头不存在")
    if not cam.enabled:
        raise HTTPException(status_code=409, detail="摄像头已停用，请先在设备管理启用")
    return cam


@router.get("/streams/status")
def streams_status(request: Request):
    """当前所有采集通道的状态：观看人数、是否取到实流、重连次数、打开失败原因。"""
    _authenticate_video(request)
    hubs = getattr(request.app.state, "hubs", None)
    return {"streams": hubs.stats() if hubs is not None else []}


@router.get("/preview/stream")
def camera_preview(
    request: Request,
    source: str = "",
    username: str = "",
    password: str = "",
    fps: int = 12,
    annotate: bool = False,
):
    """免落库的临时预览：添加/配置摄像头前，先用来源（与凭据）验证是否可取流。

    不会写入配置，也不会污染已配置的摄像头列表——内部用临时 camera_id 走同一套
    FrameHub 采集与渲染逻辑（含凭据注入、取流失败降级仿真），流关闭后立即作废该临时连接。
    """
    _authenticate_video(request)
    if not source or not source.strip():
        raise HTTPException(status_code=400, detail="source 不能为空")
    hubs = request.app.state.hubs
    # 临时摄像头对象：类型按来源推断（rtsp://→rtsp，http://→http，纯数字→usb）
    cam = CameraInfo(
        id=f"__preview__{abs(hash(source + '|' + username))}",
        name="临时预览",
        type=CameraType(normalize_camera_type(infer_camera_type(source))),
        source=source.strip(),
        enabled=True,
        username=username or None,
        password=password or None,
    )
    hub = hubs.acquire(cam)

    def _cleanup() -> None:
        try:
            hubs.release(hub)
        except Exception:
            pass
        try:
            hubs.invalidate(cam.id)  # 临时连接，关闭即作废，不留 linger
        except Exception:
            pass

    streamer = VideoStreamer(
        cam,
        hub,
        annotate=annotate,
        engine=None,
        on_close=_cleanup,
    )
    return StreamingResponse(
        streamer.stream(fps=fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/{cam_id}/video")
def camera_video(cam_id: str, request: Request, fps: int = 15, annotate: bool = True):
    # 鉴权与校验都在生成器之外完成，确保错误能以正常 HTTP 状态码返回
    _authenticate_video(request)
    cam = _require_camera(request, cam_id)

    hubs = request.app.state.hubs
    hub = hubs.acquire(cam)
    streamer = VideoStreamer(
        cam,
        hub,
        annotate=annotate,
        engine=getattr(request.app.state, "engine", None),
        on_close=lambda: hubs.release(hub),
    )
    return StreamingResponse(
        streamer.stream(fps=fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/{cam_id}/snapshot")
def camera_snapshot(cam_id: str, request: Request, annotate: bool = True, quality: int = 85):
    """取单帧 JPEG。用于设备列表缩略图、报告插图，以及"这台摄像头到底通不通"的快速自检。"""
    _authenticate_video(request)
    cam = _require_camera(request, cam_id)

    hubs = request.app.state.hubs
    hub = hubs.acquire(cam)
    try:
        img, meta = render_frame(
            hub, cam, annotate=annotate, engine=getattr(request.app.state, "engine", None)
        )
        if img is None:
            raise HTTPException(status_code=503, detail="暂时取不到画面，请稍后重试")
        payload = encode_jpeg(img, quality)
        if payload is None:
            raise HTTPException(status_code=500, detail="画面编码失败")
    finally:
        hubs.release(hub)
    return Response(
        content=payload,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Frame-Source": "real" if meta.get("is_real") else "synthetic",
        },
    )
