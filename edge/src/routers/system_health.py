from fastapi import APIRouter, Depends, Request

from ..auth import get_current_user
from ..models import User
from ..system_monitor import get_system_health

router = APIRouter(prefix="/system-health", tags=["system"], dependencies=[Depends(get_current_user)])


@router.get("")
def system_health(request: Request):
    return get_system_health()
