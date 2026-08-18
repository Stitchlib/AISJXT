"""视频流接口：把摄像头画面以 MJPEG 推给前端，真正解决"看不到画面"。

端点：
- GET /cameras/{cam_id}/video  -> multipart/x-mixed-replace MJPEG 实时画面

鉴权：MJPEG 经 <img src> 拉取，无法附带 Authorization 头，故支持 ?token= 查询参数；
也兼容标准 Authorization: Bearer 头。无效则 401。token 即登录后前端持有的 JWT。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..camera_capture import open_provider
from ..models import CameraType
from ..video_stream import VideoStreamer

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


@router.get("/{cam_id}/video")
def camera_video(cam_id: str, request: Request, fps: int = 15):
    # 鉴权（同步依赖，避免在生成器内做 IO）
    _authenticate_video(request)

    cam = request.app.state.cam.get(cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="摄像头不存在")
    if not cam.enabled:
        raise HTTPException(status_code=409, detail="摄像头已停用，请先在设备管理启用")

    provider = None
    # 仅真实类型尝试开流；仿真类型直接走合成画面
    if cam.type in (CameraType.USB, CameraType.IP, CameraType.NETWORK):
        try:
            provider = open_provider(cam.source)
        except Exception as e:
            logger.warning("摄像头 %s 打开失败，降级合成画面: %s", cam_id, e)
            provider = None

    streamer = VideoStreamer(cam, provider)
    return StreamingResponse(
        streamer.stream(fps=fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )
