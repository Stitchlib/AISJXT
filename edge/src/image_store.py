"""缺陷图片留存（第二期 G1）：带标注帧落盘、配额/保留期治理、安全读取。

职责边界：
- save()：把检测帧（叠加缺陷框）编码 JPEG 写入 images/{camera_id}/{日期}/{时刻}.jpg；
- cleanup()：按保留天数 + 容量配额双通道清理，先到先清，防止边缘设备磁盘打爆；
- resolve_safe()：媒体访问端点的路径白名单校验（必须位于根目录内，防路径穿越）。

图片目录默认与数据库同级的 images/，可通过配置/环境变量显式指定。
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("image_store")

# 保存模式（与配置 save_image_mode 一致）
MODE_NONE = "none"
MODE_DEFECT_ONLY = "defect_only"
MODE_ALL = "all"
MODE_SAMPLE = "sample"
_VALID_MODES = {MODE_NONE, MODE_DEFECT_ONLY, MODE_ALL, MODE_SAMPLE}
_SAMPLE_EVERY = 10  # sample 模式：每 N 帧保存一张

# camera_id 进入目录名前消毒（只保留字母数字、下划线、连字符、点）
_UNSAFE_DIR = re.compile(r"[^A-Za-z0-9_.\-]+")

# 视频帧渲染（复用既有的中文标注绘制），失败时模块仍可导入（无 cv2 环境不出图）
try:
    from .video_stream import draw_detections, encode_jpeg

    _RENDER = True
except Exception:  # pragma: no cover - 无 cv2/Pillow 环境
    _RENDER = False
    draw_detections = None
    encode_jpeg = None


def _utc_now_dirname() -> tuple[str, str]:
    """返回 (日期目录名, 文件名时间戳)，UTC 时间避免跨时区目录混乱。"""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d"), now.strftime("%H%M%S") + f"_{int(now.microsecond / 1000):03d}"


class ImageStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._tick = 0  # sample 模式抽样计数

    @classmethod
    def from_config(cls, cfg, db) -> "ImageStore":
        """按配置解析图片根目录：显式 image_dir > 数据库同级的 images/。

        db_path 用 getattr 兜底（单测用 FakeDB 时回退默认路径）。
        """
        db_path = getattr(db, "db_path", None) or "data/inspection.db"
        if cfg.image_dir:
            root = Path(cfg.image_dir)
            if not root.is_absolute():
                # 相对路径基于数据库所在目录解析，避免受启动工作目录影响
                root = Path(db_path).resolve().parent / root
        else:
            root = Path(db_path).resolve().parent / "images"
        return cls(root)

    # ---------- 保存 ----------
    @staticmethod
    def _safe_dir_name(camera_id: str) -> str:
        name = _UNSAFE_DIR.sub("_", str(camera_id or "cam")).strip("_")
        return name[:64] or "cam"

    def should_save(self, mode: str, defect_count: int) -> bool:
        """按保存模式判断本帧是否落盘。sample 模式内部维护抽样计数。"""
        if mode not in _VALID_MODES:
            mode = MODE_DEFECT_ONLY
        if mode == MODE_NONE:
            return False
        if mode == MODE_ALL:
            return True
        if mode == MODE_DEFECT_ONLY:
            return defect_count > 0
        # sample：每 _SAMPLE_EVERY 帧保存一张（无论有无缺陷，便于复盘正常帧）
        self._tick += 1
        if self._tick % _SAMPLE_EVERY == 0:
            return True
        return defect_count > 0

    def save(self, frame, defects, camera_id: str, quality: int = 82) -> Optional[str]:
        """把带标注的帧落盘，返回绝对路径；帧为空或编码失败返回 None（绝不影响检测主链路）。"""
        if not _RENDER or frame is None:
            return None
        try:
            img = frame.copy()
            draw_detections(img, defects)
            payload = encode_jpeg(img, quality)
            if not payload:
                return None
            day_dir, ts_name = _utc_now_dirname()
            dest = self.root / self._safe_dir_name(camera_id) / day_dir / f"{ts_name}.jpg"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(payload)
            return str(dest)
        except Exception as e:
            logger.warning("缺陷图片保存失败（不影响检测）: %s", e)
            return None

    # ---------- 治理 ----------
    def cleanup(self, retention_days: int, quota_gb: float) -> dict:
        """双通道清理：先删超保留期的，再在超配额时按最旧优先删到配额内。

        返回 {"by_age": n1, "by_quota": n2, "removed": n1+n2}。失败不抛异常（治理不阻断服务）。
        """
        removed_age = 0
        removed_quota = 0
        try:
            if not self.root.exists():
                return {"by_age": 0, "by_quota": 0, "removed": 0}
            files = [p for p in self.root.rglob("*.jpg") if p.is_file()]
            now = time.time()
            # 通道一：保留期（按文件 mtime）
            if retention_days and retention_days > 0:
                cutoff = now - retention_days * 86400
                for p in files:
                    try:
                        if p.stat().st_mtime < cutoff:
                            p.unlink()
                            removed_age += 1
                    except (OSError, SystemExit):
                        continue
                files = [p for p in files if p.exists()]
            # 通道二：容量配额（最旧优先，直到回到配额内）
            if quota_gb and quota_gb > 0:
                limit = quota_gb * 1024**3
                sized = []
                total = 0
                for p in files:
                    try:
                        s = p.stat().st_size
                        sized.append((p, s))
                        total += s
                    except OSError:
                        continue
                if total > limit:
                    sized.sort(key=lambda x: x[0].stat().st_mtime)  # 最旧在前
                    for p, s in sized:
                        if total <= limit:
                            break
                        try:
                            p.unlink()
                            total -= s
                            removed_quota += 1
                        except (OSError, SystemExit):
                            continue
            # 清理空目录（日期/摄像头层级）
            for dirpath in sorted(
                (d for d in self.root.rglob("*") if d.is_dir()),
                key=lambda d: len(d.parts),
                reverse=True,
            ):
                try:
                    dirpath.rmdir()  # 仅空目录可删，非空自动失败
                except (OSError, SystemExit):
                    continue
        except (Exception, SystemExit) as e:  # pragma: no cover - 治理失败不阻断
            logger.warning("图片清理异常: %s", e)
        removed = removed_age + removed_quota
        if removed:
            logger.info("图片清理完成: 按保留期删 %d 张, 按配额删 %d 张", removed_age, removed_quota)
        return {"by_age": removed_age, "by_quota": removed_quota, "removed": removed}

    # ---------- 安全读取 ----------
    def resolve_safe(self, rel_path: str) -> Optional[Path]:
        """媒体端点用：把路径（DB 存的绝对路径或相对路径）解析为根目录内的文件。

        任何穿越企图（../ 等）或根目录外的绝对路径都返回 None；只允许 jpg。
        """
        if not rel_path:
            return None
        try:
            root = self.root.resolve()
            p = Path(rel_path)
            candidate = p.resolve() if p.is_absolute() else (root / p).resolve()
        except (OSError, ValueError):
            return None
        # 必须位于根目录内（严格小于根的子路径），且只允许 jpg
        if candidate == root or root not in candidate.parents:
            return None
        if candidate.suffix.lower() != ".jpg":
            return None
        if not candidate.is_file():
            return None
        return candidate
