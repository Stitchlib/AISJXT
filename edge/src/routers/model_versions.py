import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from ..auth import get_current_user, require_admin, require_operator
from ..models import ModelVersion, User
from ..sample_export import build_yolo_zip

router = APIRouter(prefix="/model-versions", tags=["model"], dependencies=[Depends(get_current_user)])

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "model"
_ALLOWED_EXT = {".pt"}
_CHUNK = 1024 * 1024  # 1MB 分块读，避免一次性载入内存（M4）


class ModelVersionMeta(BaseModel):
    name: str
    version: str = "1.0.0"
    metric: float = 0.0
    description: str = ""
    activate: bool = False


def _validate_model_load(path: str):
    """校验权重可加载（M4）：若环境具备 ultralytics 则尝试 YOLO 加载。

    返回：True=通过；None=无法校验（依赖缺失，放行）；Exception=加载失败（应拒绝）。
    """
    try:
        from ultralytics import YOLO  # 惰性导入
    except Exception:
        return None
    try:
        YOLO(path)
        return True
    except Exception as e:  # 权重损坏/类别不匹配等
        return e


@router.get("")
def list_versions(request: Request):
    versions = [ModelVersion(**v) for v in request.app.state.db.list_model_versions()]
    active = request.app.state.db.get_active_model_version()
    return {"items": versions, "active_id": active["id"] if active else None}


@router.post("/upload", response_model=ModelVersion, status_code=201)
async def upload(
    file: UploadFile = File(...),
    name: str = Form(...),
    version: str = Form("1.0.0"),
    metric: float = Form(0.0),
    description: str = Form(""),
    activate: bool = Form(False),
    request: Request = None,
    _admin: User = Depends(require_admin),
):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少模型文件")
    safe_name = Path(file.filename).name
    ext = Path(safe_name).suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"仅允许上传 {', '.join(_ALLOWED_EXT)} 权重文件")
    max_mb = request.app.state.cm.get().max_upload_mb
    max_bytes = max_mb * 1024 * 1024
    dest = MODEL_DIR / safe_name

    # 流式分块落盘 + 大小硬限制（M4）：超限立即中止并清理，避免 OOM 与任意文件写入
    written = 0
    try:
        with open(dest, "wb") as f:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    f.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413, detail=f"模型文件超过上限 {max_mb}MB（实际约 {written // (1024*1024)}MB）"
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"模型文件写入失败: {e}")

    mv_id = request.app.state.db.create_model_version({
        "name": name, "version": version, "metric": metric,
        "description": description, "file_path": str(dest), "active": False,
    })
    if activate:
        await _do_activate(request, mv_id)
    _audit(request, _admin.username, "model_versions.upload", name, f"file={safe_name} activate={activate}")
    return ModelVersion(**request.app.state.db.get_model_version(mv_id))


async def _do_activate(request: Request, mv_id: int) -> None:
    db = request.app.state.db
    mv = db.get_model_version(mv_id)
    if not mv:
        raise HTTPException(status_code=404, detail="模型版本不存在")
    # 激活前校验权重可加载（M4）：依赖可用才校验，避免在缺依赖环境误拒
    verdict = await asyncio.to_thread(_validate_model_load, mv["file_path"])
    if isinstance(verdict, Exception):
        raise HTTPException(status_code=400, detail=f"模型加载校验失败，未激活：{verdict}")
    db.set_active_model_version(mv_id)
    request.app.state.cm.update(model_path=mv["file_path"], enable_simulation=False)
    request.app.state.engine.reload_detector()


@router.post("/{mv_id}/activate")
async def activate(mv_id: int, request: Request, _admin: User = Depends(require_admin)):
    await _do_activate(request, mv_id)
    _audit(request, _admin.username, "model_versions.activate", str(mv_id), "权重已激活")
    return {"ok": True, "active_id": mv_id}


@router.delete("/{mv_id}")
def delete_version(
    mv_id: int, request: Request, _admin: User = Depends(require_admin)
):
    db = request.app.state.db
    mv = db.get_model_version(mv_id)
    if not mv:
        raise HTTPException(status_code=404, detail="模型版本不存在")
    # L5：禁止删除当前激活中的模型版本，避免行为未定义
    active = db.get_active_model_version()
    if active and active["id"] == mv_id:
        raise HTTPException(status_code=400, detail="不能删除正在使用的激活模型版本")
    fp = mv.get("file_path")
    if fp:
        p = Path(fp)
        if p.exists() and MODEL_DIR in p.resolve().parents:
            try:
                p.unlink()
            except Exception:
                pass
    db.delete_model_version(mv_id)
    _audit(request, _admin.username, "model_versions.delete", str(mv_id), mv.get("name", ""))
    return {"ok": True, "removed": mv_id}


def _audit(request: Request, actor: str, action: str, target: str, detail: str) -> None:
    try:
        request.app.state.audit.record(
            actor=actor, action=action, target=target, detail=detail,
            ip=request.client.host if request.client else "",
        )
    except Exception:
        pass


@router.get("/export-samples")
async def export_samples(
    verdicts: str = "confirmed,false_positive",
    limit: int = 2000,
    request: Request = None,
    _op: User = Depends(require_operator),
):
    """训练样本导出（第二期 1.3）：把已判定（confirmed/false_positive）的缺陷帧 + 标注
    转 YOLO 目录结构并打包 zip 下载，直接用于 ``ultralytics train``。

    - 样本来源：alert_events 中 verdict ∈ {confirmed, false_positive} 且关联 detection_results 已落盘；
    - 配额保护：单次导出数不超过配置 sample_export_limit（默认 2000），防止超大 zip。
    """
    db = request.app.state.db
    cap = getattr(request.app.state.cm.get(), "sample_export_limit", 2000) or 2000
    want = max(1, int(limit))
    want = min(want, cap)
    vs = [v.strip() for v in verdicts.split(",") if v.strip()] or ["confirmed", "false_positive"]
    rows = db.export_sample_rows(vs, want)
    data, written = build_yolo_zip(rows, limit=want)
    _audit(
        request, _op.username, "model_versions.export_samples",
        f"verdicts={','.join(vs)} count={written}", "导出 YOLO 训练样本",
    )
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="training_samples_{written}.zip"'},
    )
