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
    admin: User = Depends(_require_admin),
    auth: AuthService = Depends(get_auth_service),
):
    uid = auth.create_user(body.username, body.password, body.display_name, body.role)
    return auth.get_user(body.username)


@router.put("/{user_id}", response_model=User)
def update_user(
    user_id: int,
    body: UpdateUserReq,
    admin: User = Depends(_require_admin),
    auth: AuthService = Depends(get_auth_service),
):
    if not auth.update_user(user_id, **body.model_dump(exclude_unset=True)):
        raise HTTPException(status_code=404, detail="用户不存在")
    # 通过 list 反查该 id
    for u in auth.list_users():
        if u["id"] == user_id:
            return User(
                id=u["id"], username=u["username"], display_name=u.get("display_name", ""),
                role=UserRole(u["role"]), disabled=bool(u["disabled"]), created_at=u.get("created_at", ""),
            )
    raise HTTPException(status_code=404, detail="用户不存在")


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    admin: User = Depends(_require_admin),
    auth: AuthService = Depends(get_auth_service),
):
    if not auth.delete_user(user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"ok": True, "removed": user_id}
