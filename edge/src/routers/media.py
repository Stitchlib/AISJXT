"""缺陷图片访问端点（第二期 G1）。

- GET /media/{rel_path}：读取留存的缺陷现场图（带标注 JPEG）。
  鉴权：标准 Bearer（axios blob 场景）或一次性 ?ticket=（<img> 直连场景，复用 stream_tickets）。
  安全：路径经 ImageStore.resolve_safe 白名单校验，任何穿越企图（../ 等）返回 404/403。
- GET /media/root-info：当前图片留存配置与磁盘占用（运维排障用）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..stream_tickets import authenticate

router = APIRouter(prefix="/media", tags=["media"])


class MediaRootInfo(BaseModel):
    save_image_mode: str
    image_quota_gb: float
    image_retention_days: int
    image_dir: str
    disk_usage_bytes: int


def _images(request: Request):
    store = getattr(request.app.state, "images", None)
    if store is None:
        raise HTTPException(status_code=503, detail="图片留存未启用")
    return store


@router.get("/root-info", response_model=MediaRootInfo)
def root_info(request: Request):
    authenticate(request, request.app.state.auth)
    store = _images(request)
    cfg = request.app.state.cm.get()
    usage = 0
    if store.root.exists():
        for p in store.root.rglob("*.jpg"):
            try:
                usage += p.stat().st_size
            except OSError:
                continue
    return MediaRootInfo(
        save_image_mode=cfg.save_image_mode,
        image_quota_gb=cfg.image_quota_gb,
        image_retention_days=cfg.image_retention_days,
        image_dir=str(store.root),
        disk_usage_bytes=usage,
    )


@router.get("/{rel_path:path}")
def get_image(rel_path: str, request: Request):
    authenticate(request, request.app.state.auth)
    store = _images(request)
    resolved = store.resolve_safe(rel_path)
    if resolved is None:
        # 路径不合法/不存在统一 404，避免探测目录结构
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(resolved, media_type="image/jpeg")
