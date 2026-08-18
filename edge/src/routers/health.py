from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request):
    return {
        "status": "ok",
        "service": "ai-visual-inspection",
        "version": "1.0.0",
        "websocket_clients": request.app.state.ws.count(),
    }
