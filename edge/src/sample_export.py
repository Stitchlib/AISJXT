"""训练样本导出（第二期 1.3）：把已判定的缺陷帧 + 标注转 YOLO 训练目录结构并打包 zip。

闭环位置：G1 缺陷图留存 → G2 人工判定（confirmed/false_positive）→ 本模块导出 YOLO 样本，
直接喂给 ``ultralytics train`` 完成模型迭代闭环。

输出结构（zip 内）：
    images/000000.jpg, 000001.jpg, ...
    labels/000000.txt, 000001.txt, ...   # 每行: <class_id> <x_center> <y_center> <width> <height> (归一化)
    classes.txt                            # 类别名，按出现顺序
    data.yaml                             # ultralytics 可直接读取

坐标转换：detection_results.defects 的 bbox 为像素坐标、左上角原点 (x, y, width, height)；
YOLO 要求归一化中心坐标，故 xc=(x+w/2)/W、yc=(y+h/2)/H、nw=w/W、nh=h/H。
图片尺寸优先用 PIL 读取，缺失时回退 opencv；二者皆无则跳过该框（避免无效标注）。
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

try:
    from PIL import Image  # 惰性导入：ultralytics 依赖 Pillow，一般可用

    _HAVE_PIL = True
except Exception:  # pragma: no cover - 无 Pillow 环境
    _HAVE_PIL = False


def _image_size(path: Path) -> Optional[Tuple[int, int]]:
    """返回 (width, height)；读取失败返回 None。"""
    if _HAVE_PIL:
        try:
            with Image.open(path) as im:
                return im.width, im.height
        except Exception:
            pass
    try:  # 回退：opencv（requirements 含 opencv-python-headless）
        import cv2  # type: ignore

        arr = cv2.imread(str(path))
        if arr is not None:
            h, w = arr.shape[:2]
            return w, h
    except Exception:
        pass
    return None


def _bbox_to_yolo(bbox: dict, w: int, h: int) -> Optional[Tuple[float, float, float, float]]:
    """像素左上角 bbox -> 归一化中心 bbox；非法/零尺寸返回 None。"""
    try:
        x = float(bbox["x"])
        y = float(bbox["y"])
        bw = float(bbox["width"])
        bh = float(bbox["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if w <= 0 or h <= 0 or bw <= 0 or bh <= 0:
        return None
    xc = min(max((x + bw / 2.0) / w, 0.0), 1.0)
    yc = min(max((y + bh / 2.0) / h, 0.0), 1.0)
    nw = min(max(bw / w, 0.0), 1.0)
    nh = min(max(bh / h, 0.0), 1.0)
    return (xc, yc, nw, nh)


def build_yolo_zip(rows: Iterable[dict], limit: Optional[int] = None) -> Tuple[bytes, int]:
    """把样本行（{image_path, defects}）打包为 YOLO 目录 zip。

    返回 (zip_bytes, 实际写入图片数)。图片缺失/读尺寸失败会跳过该样本，不中断整体。
    """
    mem = io.BytesIO()
    classes: List[str] = []
    class_idx: dict = {}
    count = 0
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            if limit is not None and count >= limit:
                break
            img_path = row.get("image_path")
            if not img_path:
                continue
            p = Path(img_path)
            if not p.is_file():
                continue
            defects = row.get("defects") or []
            if isinstance(defects, str):
                try:
                    defects = json.loads(defects)
                except Exception:
                    defects = []
            if not isinstance(defects, list):
                defects = []
            size = _image_size(p)
            label_lines: List[str] = []
            for d in defects:
                cls = d.get("class_name") if isinstance(d, dict) else None
                bbox = d.get("bbox") if isinstance(d, dict) else None
                if not cls or not isinstance(bbox, dict):
                    continue
                if cls not in class_idx:
                    class_idx[cls] = len(classes)
                    classes.append(cls)
                if size is None:
                    continue  # 无尺寸无法归一化，跳过该框（仍记录类别占位已在上方）
                yolo = _bbox_to_yolo(bbox, size[0], size[1])
                if yolo is None:
                    continue
                label_lines.append(
                    f"{class_idx[cls]} {yolo[0]:.6f} {yolo[1]:.6f} {yolo[2]:.6f} {yolo[3]:.6f}"
                )
            # 图片可能已不存在于磁盘但 DB 仍记录 -> 上面的 is_file 拦截
            try:
                zf.writestr(f"images/{count:06d}.jpg", p.read_bytes())
            except Exception:
                continue
            zf.writestr(f"labels/{count:06d}.txt", "\n".join(label_lines))
            count += 1
        # 类映射 + ultralytics data.yaml
        zf.writestr("classes.txt", "\n".join(classes))
        yaml_lines = [
            "path: .",
            "train: images",
            f"nc: {len(classes)}",
            "names: [" + ", ".join(repr(c) for c in classes) + "]",
        ]
        zf.writestr("data.yaml", "\n".join(yaml_lines))
    return mem.getvalue(), count
