from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, get_auth_service, get_current_user
from ..models import User, UserRole

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(get_current_user)])


class CreateUserReq(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: UserRole = UserRole.OPERATOR


class UpdateUserReq(BaseModel):
    display_name: str | None = None
    role: UserRole | None = None
    disabled: bool | None = None


class PasswordReq(BaseModel):
    # 修改他人（admin）只需 new_password；修改自己需提供 old_password 校验
    old_password: str | None = None
    new_password: str


def _require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@router.get("", response_model=list[User])
def list_users(admin: User = Depends(_require_admin), auth: AuthService = Depends(get_auth_service)):
    return [
        User(
            id=u["id"], username=u["username"], display_name=u.get("display_name", ""),
            role=UserRole(u["role"]), disabled=bool(u["disabled"]), created_at=u.get("created_at", ""),
        )
        for u in auth.list_users()
    ]


@router.post("", response_model=User, status_code=201)
def create_user(
    body: CreateUserReq,
    request: Request,
    admin: User = Depends(_require_admin),
    auth: AuthService = Depends(get_auth_service),
):
    auth.create_user(body.username, body.password, body.display_name, body.role)
    _audit(request, admin.username, "users.create", body.username, f"role={body.role.value}")
    return auth.get_user(body.username)


@router.put("/{user_id}", response_model=User)
def update_user(
    user_id: int,
    body: UpdateUserReq,
    request: Request,
    admin: User = Depends(_require_admin),
    auth: AuthService = Depends(get_auth_service),
):
    if not auth.update_user(user_id, **body.model_dump(exclude_unset=True)):
        raise HTTPException(status_code=404, detail="用户不存在")
    _audit(request, admin.username, "users.update", str(user_id), ",".join(body.model_dump(exclude_unset=True).keys()))
    for u in auth.list_users():
        if u["id"] == user_id:
            return User(
                id=u["id"], username=u["username"], display_name=u.get("display_name", ""),
                role=UserRole(u["role"]), disabled=bool(u["disabled"]), created_at=u.get("created_at", ""),
            )
    raise HTTPException(status_code=404, detail="用户不存在")


@router.put("/{user_id}/password")
def change_password(
    user_id: int,
    body: PasswordReq,
    request: Request,
    current: User = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
):
    """修改口令（M6）：admin 可改任意用户；本人修改需校验旧口令。"""
    target = next((u for u in auth.list_users() if u["id"] == user_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if current.role != UserRole.ADMIN and current.username != target["username"]:
        raise HTTPException(status_code=403, detail="无权修改该用户口令")
    if current.username == target["username"]:
        # 本人修改必须校验旧口令
        if not auth.authenticate(target["username"], body.old_password or ""):
            raise HTTPException(status_code=400, detail="旧口令校验失败")
    if not body.new_password or len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="新口令至少 6 位")
    auth.force_set_user_password(user_id, body.new_password)
    _audit(request, current.username, "users.password", target["username"], "口令已更新")
    return {"ok": True}


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    admin: User = Depends(_require_admin),
    auth: AuthService = Depends(get_auth_service),
):
    # M6 防护：禁止删除自己、禁止删除最后一个 admin
    target = next((u for u in auth.list_users() if u["id"] == user_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target["username"] == admin.username:
        raise HTTPException(status_code=400, detail="不能删除当前登录的管理员账号")
    if target["role"] == UserRole.ADMIN.value:
        admins = [u for u in auth.list_users() if u["role"] == UserRole.ADMIN.value]
        if len(admins) <= 1:
            raise HTTPException(status_code=400, detail="不能删除最后一个管理员账号")
    if not auth.delete_user(user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    _audit(request, admin.username, "users.delete", target["username"], "用户已删除")
    return {"ok": True, "removed": user_id}


def _audit(request: Request, actor: str, action: str, target: str, detail: str) -> None:
    try:
        request.app.state.audit.record(
            actor=actor, action=action, target=target, detail=detail,
            ip=request.client.host if request.client else "",
        )
    except Exception:
        pass
