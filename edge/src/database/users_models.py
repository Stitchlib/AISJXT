"""用户与模型版本域：账号 CRUD（认证/RBAC 配套）与模型版本登记/激活。"""
from __future__ import annotations

from typing import List

from ..models import utc_iso


class UsersModelsMixin:
    # ---------- 用户 ----------
    def get_user_by_username(self, username: str) -> dict | None:
        with self._conn_cm() as conn:
            row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            return dict(row) if row else None

    def set_user_password_by_username(self, username: str, salt_hex: str, hash_hex: str) -> bool:
        with self._conn_cm() as conn:
            cur = conn.execute(
                "UPDATE users SET salt=?, password_hash=? WHERE username=?",
                (salt_hex, hash_hex, username),
            )
            conn.commit()
            return cur.rowcount > 0

    def get_user_by_id(self, user_id: int) -> dict | None:
        with self._conn_cm() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def create_user(self, username, display_name, role, salt_hex, hash_hex, disabled=False) -> int:
        with self._conn_cm() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, display_name, role, disabled, created_at, salt, password_hash) VALUES (?,?,?,?,?,?,?)",
                (username, display_name, role, int(disabled), utc_iso(), salt_hex, hash_hex),
            )
            conn.commit()
            return cur.lastrowid

    def list_users(self) -> List[dict]:
        with self._conn_cm() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT id,username,display_name,role,disabled,created_at FROM users ORDER BY id"
            ).fetchall()]

    def update_user(self, user_id: int, **fields) -> bool:
        allowed = ["display_name", "role", "disabled"]
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "disabled" in sets:
            sets["disabled"] = int(sets["disabled"])
        if not sets:
            return False
        cols = ", ".join(f"{k}=?" for k in sets)
        vals = [sets[k] for k in sets] + [user_id]
        with self._conn_cm() as conn:
            conn.execute(f"UPDATE users SET {cols} WHERE id=?", vals)
            conn.commit()
            return True

    def delete_user_by_id(self, user_id: int) -> bool:
        with self._conn_cm() as conn:
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            conn.commit()
            return True

    def count_users(self) -> int:
        with self._conn_cm() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # ---------- 模型版本 ----------
    def list_model_versions(self) -> List[dict]:
        with self._conn_cm() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM model_versions ORDER BY id DESC").fetchall()]

    def get_model_version(self, mv_id: int) -> dict | None:
        with self._conn_cm() as conn:
            row = conn.execute("SELECT * FROM model_versions WHERE id=?", (mv_id,)).fetchone()
            return dict(row) if row else None

    def create_model_version(self, mv: dict) -> int:
        with self._conn_cm() as conn:
            cur = conn.execute(
                "INSERT INTO model_versions (name,version,file_path,metric,active,description,created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    mv["name"], mv.get("version", "1.0.0"), mv.get("file_path", ""),
                    mv.get("metric", 0.0), int(mv.get("active", False)), mv.get("description", ""),
                    mv.get("created_at", utc_iso()),
                ),
            )
            conn.commit()
            return cur.lastrowid

    def set_active_model_version(self, mv_id: int) -> None:
        with self._conn_cm() as conn:
            conn.execute("UPDATE model_versions SET active=0")
            conn.execute("UPDATE model_versions SET active=1 WHERE id=?", (mv_id,))
            conn.commit()

    def get_active_model_version(self) -> dict | None:
        with self._conn_cm() as conn:
            row = conn.execute("SELECT * FROM model_versions WHERE active=1 LIMIT 1").fetchone()
            return dict(row) if row else None

    def delete_model_version(self, mv_id: int) -> bool:
        with self._conn_cm() as conn:
            conn.execute("DELETE FROM model_versions WHERE id=?", (mv_id,))
            conn.commit()
            return True
