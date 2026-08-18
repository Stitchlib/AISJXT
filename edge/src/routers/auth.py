from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import AuthService, get_auth_service, get_current_user
from ..models import LoginRequest, Token, User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(req: LoginRequest, auth: AuthService = Depends(get_auth_service)):
    token = auth.login(req)
    if not token:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return token


@router.get("/me", response_model=User)
def me(user: User = Depends(get_current_user)):
    return user
