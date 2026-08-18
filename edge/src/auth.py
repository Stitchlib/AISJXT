"""认证与权限：JWT 无状态鉴权 + 用户存储（由 Database 提供）。

设计要点：
- 密码哈希：pbkdf2_hmac(SHA256) 加盐，标准库实现，零额外依赖、跨平台稳定。
- Token：PyJWT(HS256)，密钥来自配置 secret_key（生产务必环境变量覆盖）。
- get_current_user 作为 FastAPI 依赖挂在受保护路由上；缺失/失效令牌返回 401。
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import logging

from fastapi import HTTPException, Request

from .config_manager import ConfigManager
from .database import Database
from .models import LoginRequest, Token, User, UserRole

logger = logging.getLogger("auth")


class AuthService:
    def __init__(self, db: Database, cm: ConfigManager) -> None:
        self._db = db
        self._cm = cm
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
        except Exception as e:  # pragma: no cover - 极端初始化失败
            logger and logger.warning("admin 种子失败: %s", e)

    # ---- 认证 ----
    def authenticate(self, username: str, password: str) -> Optional[User]:
        row = self._db.get_user_by_username(username)
        if not row or row["disabled"]:
            return None
        if not _verify_password(password, row["salt"], row["password_hash"]):
            return None
        return _row_to_user(row)

    def login(self, req: LoginRequest) -> Optional[Token]:
        u = self.authenticate(req.username, req.password)
        if not u:
            return None
        token = _create_token(u.username, u.role.value, self._exp_min, self._secret)
        return Token(access_token=token, user=u)

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
