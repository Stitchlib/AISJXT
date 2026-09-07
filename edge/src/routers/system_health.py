from fastapi import APIRouter, Depends, Request

from ..auth import get_current_user
from ..system_monitor import get_system_health

router = APIRouter(prefix="/system-health", tags=["system"], dependencies=[Depends(get_current_user)])


@router.get("")
def system_health(request: Request):
    extra = {}
    try:
        engine = request.app.state.engine
        extra["inference_latency_ms"] = engine.latency_stats()
        extra["frame_drop_rate"] = engine.frame_drop_rate()
        extra["write_qps"] = engine.write_qps()
        extra["detector_mode"] = engine.detector_mode
    except Exception:
        pass
    try:
        extra["websocket_clients"] = request.app.state.ws.count()
    except Exception:
        pass
    try:
        import os

        db_path = request.app.state.db.db_path
        if os.path.exists(db_path):
            extra["db_size_mb"] = round(os.path.getsize(db_path) / (1024 * 1024), 2)
    except Exception:
        pass
    # 配置降级标记（M12）：配置损坏回退时对外可见
    try:
        extra["config_degraded"] = request.app.state.cm.is_degraded()
        if request.app.state.cm.is_degraded():
            extra["config_degraded_reason"] = request.app.state.cm.degraded_reason()
    except Exception:
        extra["config_degraded"] = False
    return get_system_health(extra)
