from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from ..auth import get_current_user
from ..models import ModelVersion, User

router = APIRouter(prefix="/model-versions", tags=["model"], dependencies=[Depends(get_current_user)])

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "model"


class ModelVersionMeta(BaseModel):
    name: str
    version: str = "1.0.0"
    metric: float = 0.0
    description: str = ""
    activate: bool = False


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
):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少模型文件")
    safe_name = Path(file.filename).name
    dest = MODEL_DIR / safe_name
    try:
        data = await file.read()
        dest.write_bytes(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"模型文件写入失败: {e}")
    mv_id = request.app.state.db.create_model_version({
        "name": name, "version": version, "metric": metric,
        "description": description, "file_path": str(dest), "active": activate,
    })
    if activate:
        request.app.state.db.set_active_model_version(mv_id)
        request.app.state.cm.update(model_path=str(dest), enable_simulation=False)
        request.app.state.engine.reload_detector()
    return ModelVersion(**request.app.state.db.get_model_version(mv_id))


@router.post("/{mv_id}/activate")
def activate(mv_id: int, request: Request):
    mv = request.app.state.db.get_model_version(mv_id)
    if not mv:
        raise HTTPException(status_code=404, detail="模型版本不存在")
    request.app.state.db.set_active_model_version(mv_id)
    request.app.state.cm.update(model_path=mv["file_path"], enable_simulation=False)
    request.app.state.engine.reload_detector()
    return {"ok": True, "active_id": mv_id}


@router.delete("/{mv_id}")
def delete_version(mv_id: int, request: Request):
    mv = request.app.state.db.get_model_version(mv_id)
    if not mv:
        raise HTTPException(status_code=404, detail="模型版本不存在")
    # 删除磁盘文件（若存在且属于本系统目录）
    fp = mv.get("file_path")
    if fp:
        p = Path(fp)
        if p.exists() and MODEL_DIR in p.resolve().parents:
            try:
                p.unlink()
            except Exception:
                pass
    request.app.state.db.delete_model_version(mv_id)
    return {"ok": True, "removed": mv_id}
