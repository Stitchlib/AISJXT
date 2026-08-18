from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ..auth import get_current_user
from ..models import User

router = APIRouter(prefix="/detection-results", tags=["detection"], dependencies=[Depends(get_current_user)])


@router.get("")
def list_results(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    camera_id: Optional[str] = None,
    defect_only: bool = False,
):
    page = max(1, page)
    page_size = min(max(1, page_size), 1000)
    rows, total = request.app.state.db.query_results(page, page_size, camera_id, defect_only)
    return {"page": page, "page_size": page_size, "total": total, "items": rows}


@router.get("/statistics")
def statistics(request: Request):
    return request.app.state.db.get_statistics()


@router.get("/export")
def export(request: Request, format: str = "csv"):
    if format != "csv":
        raise HTTPException(status_code=400, detail="仅支持 csv 导出")
    path = request.app.state.db.export_csv("data/export_detection_results.csv")
    return FileResponse(path, filename="detection_results.csv", media_type="text/csv")
