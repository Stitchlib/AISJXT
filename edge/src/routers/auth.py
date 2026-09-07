from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, get_auth_service, get_current_user
from ..models import LoginRequest, Token, User

router = APIRouter(prefix="/auth", tags=["auth"])


class RefreshReq(BaseModel):
    token: str  # 当前仍未过期的访问令牌


@router.post("/login", response_model=Token)
def login(req: LoginRequest, request: Request, auth: AuthService = Depends(get_auth_service)):
    token = auth.login(req)
    ip = request.client.host if request.client else ""
    try:
        request.app.state.audit.record(
            actor=req.username,
            action="auth.login",
            target="user",
            detail="登录成功" if token else "登录失败（凭据错误）",
            ip=ip,
        )
    except Exception:
        pass
    if not token:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return token


@router.post("/refresh", response_model=Token)
def refresh(req: RefreshReq, auth: AuthService = Depends(get_auth_service)):
    """滑动过期刷新（3.5）：用仍未过期的旧令牌换取新令牌，身份不变，避免长班次中途登出。"""
    new_token = auth.refresh_token(req.token)
    if not new_token:
        raise HTTPException(status_code=401, detail="令牌无效或已过期，请重新登录")
    return new_token


@router.get("/me", response_model=User)
def me(user: User = Depends(get_current_user)):
    return user
