"""认证与权限：JWT 无状态鉴权 + 用户存储（由 Database 提供）。

设计要点：
- 密码哈希：pbkdf2_hmac(SHA256) 加盐，标准库实现，零额外依赖、跨平台稳定。
- Token：PyJWT(HS256)，密钥来自配置 secret_key（生产务必环境变量覆盖）。
- get_current_user 作为 FastAPI 依赖挂在受保护路由上；缺失/失效令牌返回 401。
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import logging

from fastapi import Depends, HTTPException, Request

from .config_manager import ConfigManager
from .database import Database
from .models import LoginRequest, Token, User, UserRole

logger = logging.getLogger("auth")

# 登录失败限流（M6）：同账号连续失败达到上限后锁定一段时间（内存计数，单实例足够）。
_MAX_FAIL = 5
_LOCK_SECONDS = 10 * 60


class AuthService:
    def __init__(self, db: Database, cm: ConfigManager) -> None:
        self._db = db
        self._cm = cm
        self._fail: dict[str, list] = {}  # username -> [fail_count, lock_until_ts]
        self._seed_admin()

    # ---- 密钥与时效 ----
    @property
    def _secret(self) -> str:
        return self._cm.get().secret_key

    @property
    def _exp_min(self) -> int:
        return self._cm.get().token_expire_minutes

    # ---- 用户种子（首次启动创建 admin） ----
    def _seed_admin(self) -> None:
        try:
            if self._db.get_user_by_username("admin") is None:
                salt, h = _hash_password("admin123")
                self._db.create_user("admin", "系统管理员", UserRole.ADMIN.value, salt, h)
                logger and logger.info("已创建默认管理员账号 admin / admin123")
            # H5：若设置了环境变量 AIQC_ADMIN_PASSWORD，则用其覆盖默认口令（首次或每次启动均生效）
            env_pwd = os.environ.get("AIQC_ADMIN_PASSWORD")
            if env_pwd:
                self.force_set_admin_password(env_pwd)
                logger and logger.info("已通过环境变量 AIQC_ADMIN_PASSWORD 覆盖管理员口令")
        except Exception as e:  # pragma: no cover - 极端初始化失败
            logger and logger.warning("admin 种子失败: %s", e)

    def force_set_admin_password(self, password: str) -> bool:
        """强制设置 admin 口令（用于环境变量覆盖或运维重置）。"""
        row = self._db.get_user_by_username("admin")
        if not row:
            return False
        salt, h = _hash_password(password)
        self._db.set_user_password_by_username("admin", salt, h)
        self._fail.pop("admin", None)
        return True

    def force_set_user_password(self, user_id: int, password: str) -> bool:
        """按 id 强制设置任意用户口令（M6 改密端点使用）。"""
        row = self._db.get_user_by_id(user_id)
        if not row:
            return False
        salt, h = _hash_password(password)
        self._db.set_user_password_by_username(row["username"], salt, h)
        self._fail.pop(row["username"], None)
        return True

    # ---- 认证 ----
    def _locked_until(self, username: str) -> Optional[float]:
        rec = self._fail.get(username)
        if not rec:
            return None
        count, until = rec
        if count >= _MAX_FAIL and until and time.time() < until:
            return until
        if until and time.time() >= until:
            # 锁定期已过，重置计数
            self._fail.pop(username, None)
        return None

    def authenticate(self, username: str, password: str) -> Optional[User]:
        lock = self._locked_until(username)
        if lock is not None:
            logger.warning("账号 %s 处于登录失败锁定中，剩余 %.0fs", username, lock - time.time())
            return None
        row = self._db.get_user_by_username(username)
        if not row or row["disabled"]:
            return None
        if not _verify_password(password, row["salt"], row["password_hash"]):
            self._register_fail(username)
            return None
        # 成功登录清零失败计数
        self._fail.pop(username, None)
        return _row_to_user(row)

    def _register_fail(self, username: str) -> None:
        rec = self._fail.get(username)
        if not rec:
            rec = [0, 0.0]
            self._fail[username] = rec
        rec[0] += 1
        if rec[0] >= _MAX_FAIL:
            rec[1] = time.time() + _LOCK_SECONDS
            logger.warning("账号 %s 登录失败次数过多，已锁定 %ds", username, _LOCK_SECONDS)

    def login(self, req: LoginRequest) -> Optional[Token]:
        u = self.authenticate(req.username, req.password)
        if not u:
            return None
        token = _create_token(u.username, u.role.value, self._exp_min, self._secret)
        return Token(access_token=token, user=u)

    def refresh_token(self, token: str) -> Optional[Token]:
        """滑动过期刷新（3.5）：仅当原令牌仍有效（未过期）时签发新令牌，身份不变。"""
        payload = _decode_token(token, self._secret)
        if not payload or "sub" not in payload:
            return None
        row = self._db.get_user_by_username(payload["sub"])
        if not row or row["disabled"]:
            return None
        new_token = _create_token(row["username"], row["role"], self._exp_min, self._secret)
        return Token(access_token=new_token, user=_row_to_user(row))

    def get_current_user(self, request: Request) -> User:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="缺少认证令牌")
        payload = _decode_token(header[len("Bearer "):], self._secret)
        if not payload or "sub" not in payload:
            raise HTTPException(status_code=401, detail="令牌无效或已过期")
        row = self._db.get_user_by_username(payload["sub"])
        if not row or row["disabled"]:
            raise HTTPException(status_code=401, detail="用户不存在或已禁用")
        return _row_to_user(row)

    def get_user_from_token(self, token: Optional[str]) -> Optional[User]:
        """从裸令牌（如 MJPEG <img> URL 的 ?token= 参数）解析用户，失败返回 None。

        供视频流等无法附带 Authorization 头头的场景使用。
        """
        if not token:
            return None
        payload = _decode_token(token, self._secret)
        if not payload or "sub" not in payload:
            return None
        row = self._db.get_user_by_username(payload["sub"])
        if not row or row["disabled"]:
            return None
        return _row_to_user(row)

    # ---- 用户管理（供 users 路由调用） ----
    def create_user(self, username, password, display_name="", role=UserRole.OPERATOR, disabled=False) -> int:
        if self._db.get_user_by_username(username):
            raise HTTPException(status_code=409, detail="用户名已存在")
        salt, h = _hash_password(password)
        role_val = role.value if isinstance(role, UserRole) else role  # 兼容字符串角色
        return self._db.create_user(username, display_name, role_val, salt, h, disabled)

    def list_users(self):
        return self._db.list_users()

    def get_user(self, username: str) -> Optional[User]:
        row = self._db.get_user_by_username(username)
        return _row_to_user(row) if row else None

    def delete_user(self, user_id: int) -> bool:
        return self._db.delete_user_by_id(user_id)

    def update_user(self, user_id: int, **fields) -> bool:
        return self._db.update_user(user_id, **fields)


# ---------- 工具函数 ----------
def _hash_password(password: str, salt: Optional[bytes] = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return salt.hex(), dk.hex()


def _verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return secrets.compare_digest(dk.hex(), hash_hex)


def _create_token(username: str, role: str, expire_min: int, secret: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=expire_min),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _decode_token(token: str, secret: str) -> Optional[dict]:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except Exception:
        return None


def _row_to_user(row: dict) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        display_name=row.get("display_name", ""),
        role=UserRole(row["role"]),
        disabled=bool(row["disabled"]),
        created_at=row.get("created_at", ""),
    )


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth


def get_current_user(request: Request) -> User:
    """FastAPI 依赖：从请求头解析 Bearer Token 并返回当前用户（无效则 401）。"""
    return request.app.state.auth.get_current_user(request)


def require_admin(user: User = Depends(get_current_user)) -> User:
    """FastAPI 依赖：要求当前用户为 admin，否则 403（M5/L5 等越权防护复用）。"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_operator(user: User = Depends(get_current_user)) -> User:
    """FastAPI 依赖：要求 admin 或 operator（viewer 403）。

    供"告警人工判定"等操作类但非管理类的接口使用（第二期 G2）。
    """
    if user.role not in (UserRole.ADMIN, UserRole.OPERATOR):
        raise HTTPException(status_code=403, detail="需要操作员及以上权限")
    return user


def require_role(*allowed: UserRole):
    """权限矩阵依赖工厂（第三期 1.1/H2）：要求当前角色属于 allowed（admin 恒通过）。

    与 require_operator 的区别：
    - 可按路由粒度声明角色集（如仅 operator、仅 admin）；
    - 越权尝试写入审计日志（action=rbac_denied），供安全追溯。

    用法：Depends(require_role(UserRole.OPERATOR))
    """
    allowed_set = set(allowed) | {UserRole.ADMIN}

    def _dep(request: Request, user: User = Depends(get_current_user)) -> User:
        if user.role in allowed_set:
            return user
        # 越权尝试审计（验收④）：失败不阻断 403 响应
        try:
            request.app.state.audit.record(
                actor=user.username,
                action="rbac_denied",
                target=str(request.url.path),
                detail=f"role={user.role.value}",
                ip=request.client.host if request.client else "",
            )
        except Exception:  # pragma: no cover - 审计失败不改变响应
            pass
        raise HTTPException(status_code=403, detail="权限不足：当前角色无权执行该操作")

    return _dep
