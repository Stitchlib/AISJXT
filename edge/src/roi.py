"""ROI 检测区域处理（第二期 G6）。

ROI 以归一化矩形列表配置（见 models.RoiRect）：
- 检测前：把 ROI 并集之外的画面区域涂黑（掩膜），让检测器天然忽略区域外目标；
- 检测后：再按缺陷框中心点过滤一次，处理跨边界部分重叠的目标；
- 坐标系：全程不做裁剪缩放，检出 bbox 即原图像素坐标，前端画框位置天然一致。

无 ROI 配置时所有函数直通（行为与旧版完全一致）。
"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

logger = logging.getLogger("roi")


def _norm_rects(rois: Sequence) -> List[tuple]:
    """把 RoiRect（或等价 dict）序列转成 (x, y, w, h) float 元组，非法项跳过。"""
    out = []
    for r in rois or []:
        try:
            x = float(r.x if hasattr(r, "x") else r["x"])
            y = float(r.y if hasattr(r, "y") else r["y"])
            w = float(r.w if hasattr(r, "w") else r["w"])
            h = float(r.h if hasattr(r, "h") else r["h"])
        except (TypeError, KeyError, ValueError):
            continue
        if 0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1:
            out.append((x, y, w, h))
    return out


def apply_roi_mask(frame, rois: Sequence):
    """返回 ROI 掩膜后的帧副本：并集之外区域置黑。无 ROI 或无 numpy 时原样返回。"""
    rects = _norm_rects(rois)
    if frame is None or not rects:
        return frame
    try:
        import numpy as np
    except ImportError:  # 无 numpy 环境退化为不掩膜（检测后过滤仍生效）
        return frame
    h, w = frame.shape[:2]
    mask = np.zeros((h, w), dtype=bool)
    for x, y, rw, rh in rects:
        x1, y1 = int(x * w), int(y * h)
        x2, y2 = min(w, int((x + rw) * w)), min(h, int((y + rh) * h))
        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = True
    if mask.all():  # 全画面即 ROI：无需拷贝
        return frame
    out = frame.copy()
    out[~mask] = 0
    return out


def _center_in_rects(px: float, py: float, rects: Sequence[tuple], w: int, h: int) -> bool:
    for x, y, rw, rh in rects:
        if x * w <= px <= (x + rw) * w and y * h <= py <= (y + rh) * h:
            return True
    return False


def filter_defects_by_roi(defects: Optional[List[dict]], rois: Sequence, frame_shape) -> List[dict]:
    """保留 bbox 中心落在任一 ROI 内的缺陷；rois 为空时原样返回。"""
    rects = _norm_rects(rois)
    if not defects or not rects or not frame_shape or len(frame_shape) < 2:
        return list(defects or [])
    h, w = int(frame_shape[0]), int(frame_shape[1])
    kept = []
    for d in defects:
        try:
            bb = d.get("bbox") or {}
            cx = float(bb.get("x", 0)) + float(bb.get("width", 0)) / 2.0
            cy = float(bb.get("y", 0)) + float(bb.get("height", 0)) / 2.0
            if _center_in_rects(cx, cy, rects, w, h):
                kept.append(d)
        except (TypeError, ValueError):
            kept.append(d)  # 坐标异常的缺陷不过滤，交由后续链路处理
    return kept
