"""视频帧渲染与 MJPEG 推流。

职责：
- 生成"活的"合成画面（无实体摄像头时的布料传送带测试图），保证前端永远有画面；
- 在帧上叠加**检测缺陷框**与状态 HUD（这是视觉质检系统的核心呈现）；
- 把帧编码为 JPEG 并按 multipart/x-mixed-replace 持续输出。

中文渲染说明：OpenCV 的 `cv2.putText` 只支持 Hershey 矢量字体，**画不出中文**（会变成
一串方框/问号）。而本系统的缺陷类别（线头/跳线/色差/破洞）和摄像头名都是中文，
所以这里改用 Pillow + 系统中文字体渲染文字：先把每段文字渲染成带描边的小块 RGBA 贴片
并缓存，再用 numpy alpha 混合贴到帧上——避免每帧整图 BGR↔PIL 来回转换的开销。
Pillow 或中文字体缺失时自动退回 cv2.putText（仅 ASCII 可读），不影响出图。

帧与标注的对应关系由 frame_hub 保证：检测引擎回写 (defects, 帧序号, 检测帧尺寸)，
本模块按尺寸比例把坐标缩放到显示帧上，因此框能落在正确位置。
"""
from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from typing import Any, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger("video_stream")

try:
    import cv2
    import numpy as np

    _CV2 = True
except Exception:  # pragma: no cover - 环境无 cv2 时
    _CV2 = False
    cv2 = None
    np = None

try:
    from PIL import Image, ImageDraw, ImageFont

    _PIL = True
except Exception:  # pragma: no cover - 无 Pillow 时退回 ASCII 渲染
    _PIL = False
    Image = ImageDraw = ImageFont = None

# 候选中文字体（Windows 优先微软雅黑，其次黑体；Linux 常见开源中文字体）
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)

# 缺陷类别配色（BGR）。未知类别按名称稳定散列取色，保证同类颜色前后一致。
_DEFECT_COLORS = {
    "线头": (90, 210, 255),
    "跳线": (255, 170, 90),
    "色差": (120, 235, 160),
    "破洞": (90, 90, 255),
}
_PALETTE = (
    (90, 210, 255), (255, 170, 90), (120, 235, 160), (90, 90, 255),
    (230, 130, 240), (200, 220, 90), (110, 160, 255), (170, 120, 250),
)


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# 中文文字渲染（贴片缓存 + alpha 混合）
# --------------------------------------------------------------------------

@lru_cache(maxsize=8)
def _font(size: int):
    if not _PIL:
        return None
    for path in _FONT_CANDIDATES:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


@lru_cache(maxsize=512)
def _text_patch(text: str, size: int, color: Tuple[int, int, int]) -> Optional["np.ndarray"]:
    """把一段文字渲染成带黑色描边的 BGRA 贴片（缓存）。描边保证浅色画面上也看得清。"""
    if not (_PIL and _CV2) or not text:
        return None
    font = _font(size)
    if font is None:
        return None
    try:
        probe = Image.new("RGBA", (1, 1))
        box = ImageDraw.Draw(probe).textbbox((0, 0), text, font=font, stroke_width=2)
        pad = 3
        w = max(1, box[2] - box[0] + pad * 2)
        h = max(1, box[3] - box[1] + pad * 2)
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        rgb = (int(color[2]), int(color[1]), int(color[0]), 255)  # BGR -> RGBA
        ImageDraw.Draw(canvas).text(
            (pad - box[0], pad - box[1]),
            text,
            font=font,
            fill=rgb,
            stroke_width=2,
            stroke_fill=(0, 0, 0, 200),
        )
        arr = np.array(canvas)                 # RGBA
        return arr[:, :, [2, 1, 0, 3]].copy()  # -> BGRA
    except Exception as e:  # pragma: no cover
        logger.debug("文字贴片渲染失败: %s", e)
        return None


def _blit(img: "np.ndarray", patch: "np.ndarray", x: int, y: int) -> None:
    """把 BGRA 贴片按 alpha 混合到 BGR 图上，自动裁剪越界部分。"""
    h, w = img.shape[:2]
    x = int(max(0, min(x, w - 1)))
    y = int(max(0, min(y, h - 1)))
    ph = min(patch.shape[0], h - y)
    pw = min(patch.shape[1], w - x)
    if ph <= 0 or pw <= 0:
        return
    sub = patch[:ph, :pw]
    alpha = sub[:, :, 3:4].astype(np.float32) / 255.0
    fg = sub[:, :, :3].astype(np.float32)
    roi = img[y:y + ph, x:x + pw].astype(np.float32)
    img[y:y + ph, x:x + pw] = (fg * alpha + roi * (1.0 - alpha)).astype(np.uint8)


def draw_text(
    img: "np.ndarray",
    text: str,
    x: int,
    y: int,
    size: int = 18,
    color: Tuple[int, int, int] = (255, 255, 255),
) -> int:
    """在 (x, y) 处绘制文字（y 为文字块顶边）。返回文字块高度，便于逐行排版。"""
    if not _CV2 or not text:
        return 0
    patch = _text_patch(str(text), int(size), tuple(int(c) for c in color))
    if patch is not None:
        _blit(img, patch, x, y)
        return patch.shape[0]
    # 退化路径：无 Pillow/字体时用 cv2（中文会变方框，但仍可出图）
    scale = size / 26.0
    cv2.putText(img, str(text), (int(x), int(y + size)), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3)
    cv2.putText(img, str(text), (int(x), int(y + size)), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1)
    return size + 4


def _color_for(class_name: str) -> Tuple[int, int, int]:
    if class_name in _DEFECT_COLORS:
        return _DEFECT_COLORS[class_name]
    return _PALETTE[sum(ord(c) for c in str(class_name)) % len(_PALETTE)]


# --------------------------------------------------------------------------
# 合成画面（无实体摄像头时的测试图）
# --------------------------------------------------------------------------

_TEXTURE_CACHE: dict = {}


def _fabric_texture(h: int, w: int) -> "np.ndarray":
    """生成并缓存一张"布料"底纹（织纹 + 细噪声），用于滚动模拟传送带上的面料。"""
    key = (h, w)
    cached = _TEXTURE_CACHE.get(key)
    if cached is not None:
        return cached
    rng = np.random.default_rng(20260818)
    base = np.zeros((h, w, 3), dtype=np.float32)
    base[:, :] = (170, 178, 188)  # BGR：浅灰蓝布料
    noise = rng.normal(0.0, 5.0, (h, w, 1)).astype(np.float32)
    yy = np.arange(h, dtype=np.float32).reshape(h, 1, 1)
    xx = np.arange(w, dtype=np.float32).reshape(1, w, 1)
    weave = np.sin(yy * 1.7) * 3.2 + np.sin(xx * 1.7) * 3.2
    tex = np.clip(base + noise + weave, 0, 255).astype(np.uint8)
    _TEXTURE_CACHE[key] = tex
    return tex


def synthetic_frame(camera_id: str, name: str, t: float, size: Tuple[int, int] = (360, 640)) -> "np.ndarray":
    """生成一帧"活的"合成画面：滚动布料 + 移动扫描线，模拟传送带上的面料。

    用途明确：无实体摄像头 / 取流失败 / 重连期间的占位画面，保证前端不黑屏。
    画面上会由 HUD 明确标注"仿真画面"，绝不冒充真实采集。
    """
    if not _CV2:
        raise RuntimeError("未安装 OpenCV，无法生成合成画面")
    h, w = int(size[0]), int(size[1])
    tex = _fabric_texture(h, w)
    img = np.roll(tex, int((t * 55.0) % h), axis=0).copy()
    # 扫描线（视觉上表明画面在动，且贴合"逐帧质检"语义）
    y = int((t * 95.0) % h)
    cv2.line(img, (0, y), (w, y), (70, 205, 255), 2)
    cv2.line(img, (0, min(h - 1, y + 3)), (w, min(h - 1, y + 3)), (40, 130, 170), 1)
    # 边缘暗角，避免整图过平
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (120, 128, 138), 2)
    return img


# --------------------------------------------------------------------------
# 检测框与 HUD 叠加
# --------------------------------------------------------------------------

def draw_detections(
    frame: "np.ndarray",
    defects: Optional[Sequence[dict]],
    src_shape: Optional[Sequence[int]] = None,
) -> int:
    """在帧上绘制缺陷框与标签（原地修改）。返回实际绘制的框数。

    src_shape 为检测时所用帧的 (height, width)；与显示帧尺寸不同时按比例缩放坐标，
    这样即使检测走的是缩放后的帧，框也能落在画面正确位置。
    """
    if not _CV2 or not defects:
        return 0
    h, w = frame.shape[:2]
    sx = sy = 1.0
    if src_shape and len(src_shape) >= 2:
        sh, sw = float(src_shape[0] or 0), float(src_shape[1] or 0)
        if sh > 0 and sw > 0:
            sy, sx = h / sh, w / sw
    drawn = 0
    for d in defects:
        try:
            bb = d.get("bbox") or {}
            x1 = int(float(bb.get("x", 0)) * sx)
            y1 = int(float(bb.get("y", 0)) * sy)
            x2 = int(x1 + float(bb.get("width", 0)) * sx)
            y2 = int(y1 + float(bb.get("height", 0)) * sy)
            x1, y1 = max(0, min(x1, w - 1)), max(0, min(y1, h - 1))
            x2, y2 = max(0, min(x2, w - 1)), max(0, min(y2, h - 1))
            if x2 <= x1 or y2 <= y1:
                continue
            cls = str(d.get("class_name", "缺陷"))
            conf = float(d.get("confidence", 0) or 0)
            color = _color_for(cls)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            # 角标，让小框也醒目
            corner = max(6, min(14, (x2 - x1) // 4))
            cv2.line(frame, (x1, y1), (x1 + corner, y1), color, 4)
            cv2.line(frame, (x1, y1), (x1, y1 + corner), color, 4)
            label = f"{cls} {conf * 100:.0f}%"
            ly = y1 - 22 if y1 >= 24 else min(h - 22, y2 + 2)
            draw_text(frame, label, x1, ly, 16, color)
            drawn += 1
        except Exception:  # 单个框异常不影响其余绘制
            continue
    return drawn


def draw_hud(
    frame: "np.ndarray",
    camera_id: str,
    name: str,
    *,
    is_real: bool = False,
    detector_mode: Optional[str] = None,
    defect_count: Optional[int] = None,
    inspecting: bool = False,
    note: Optional[str] = None,
) -> None:
    """绘制状态浮层：摄像头、画面来源、检测状态、缺陷数、时间。原地修改。

    诚实标注原则：合成画面明确写"仿真画面"，标注仿真检测器明确写"标注仿真"，
    绝不让演示数据看起来像真实采集/真实推理结果。
    """
    if not _CV2:
        return
    h, w = frame.shape[:2]
    # 顶部/底部半透明条，保证文字在任何画面上都可读
    for y0, y1 in ((0, 34), (h - 30, h)):
        band = frame[y0:y1]
        if band.size:
            frame[y0:y1] = (band.astype(np.float32) * 0.45).astype(np.uint8)

    draw_text(frame, f"{name}（{camera_id}）", 10, 6, 18, (255, 255, 255))

    src_txt = "实时采集" if is_real else "仿真画面"
    src_color = (120, 235, 160) if is_real else (100, 205, 255)
    x = w - 10
    patch = _text_patch(src_txt, 16, src_color)
    if patch is not None:
        x -= patch.shape[1]
        _blit(frame, patch, x, 8)
    else:
        draw_text(frame, src_txt, w - 110, 8, 16, src_color)

    # 底部：检测状态 + 缺陷数 + 时间
    if inspecting:
        mode_txt = {"yolo": "真实模型", "simulation": "标注仿真"}.get(detector_mode or "", detector_mode or "")
        status = f"检测中 · {mode_txt}" if mode_txt else "检测中"
        status_color = (120, 235, 160) if detector_mode == "yolo" else (100, 205, 255)
    else:
        status = "检测未运行"
        status_color = (170, 170, 170)
    draw_text(frame, status, 10, h - 26, 16, status_color)

    if defect_count is not None:
        dc_color = (90, 90, 255) if defect_count > 0 else (150, 220, 150)
        dc_txt = f"本帧缺陷 {defect_count}" if defect_count > 0 else "本帧无缺陷"
        draw_text(frame, dc_txt, 150, h - 26, 16, dc_color)

    ts_patch = _text_patch(_now_str(), 16, (230, 230, 230))
    if ts_patch is not None:
        _blit(frame, ts_patch, w - ts_patch.shape[1] - 10, h - 26)
    else:
        draw_text(frame, _now_str(), w - 200, h - 26, 16, (230, 230, 230))

    if note:
        draw_text(frame, note, 10, 40, 16, (100, 205, 255))


def encode_jpeg(frame: "np.ndarray", quality: int = 82) -> Optional[bytes]:
    if not _CV2 or frame is None:
        return None
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    return buf.tobytes() if ok else None


def render_frame(
    hub,
    camera,
    *,
    annotate: bool = True,
    engine=None,
) -> Tuple[Optional["np.ndarray"], dict]:
    """从 hub 取最新帧并叠加检测框与 HUD，返回 (帧, 元信息)。

    元信息含 seq / is_real / defect_count，供快照接口与调试使用。
    """
    frame, seq, ts, is_real = hub.latest(timeout=3.0)
    if frame is None:
        return None, {"seq": 0, "is_real": False, "defect_count": None}
    img = frame.copy()
    defect_count: Optional[int] = None
    detector_mode = None
    inspecting = False
    note = None

    if engine is not None:
        try:
            inspecting = bool(getattr(engine, "running", False)) and (
                getattr(engine, "active_camera_id", None) == camera.id
            )
            detector_mode = getattr(engine, "detector_mode", None)
        except Exception:
            inspecting = False

    if annotate:
        ann = hub.annotation()
        if ann is not None:
            defect_count = draw_detections(img, ann.get("defects"), ann.get("shape"))
            inspecting = True
            detector_mode = (ann.get("meta") or {}).get("detector_mode", detector_mode)

    if not is_real and getattr(hub, "want_real", False):
        note = "摄像头未连通，正在重试"

    draw_hud(
        img,
        camera.id,
        getattr(camera, "name", "") or camera.id,
        is_real=is_real,
        detector_mode=detector_mode,
        defect_count=defect_count,
        inspecting=inspecting,
        note=note,
    )
    return img, {"seq": seq, "ts": ts, "is_real": is_real, "defect_count": defect_count}


class VideoStreamer:
    """把一路共享帧渲染为 MJPEG 输出。

    帧来源是共享的 FrameHub（一台摄像头只开一路采集），因此多个观看端不会互相抢设备。
    生成器结束（含客户端断开）时调用 on_close 归还引用，由 hub 决定何时真正释放摄像头。
    """

    def __init__(
        self,
        camera,
        hub,
        *,
        annotate: bool = True,
        quality: int = 82,
        engine=None,
        on_close=None,
    ) -> None:
        self.camera = camera
        self.hub = hub
        self.annotate = annotate
        self.quality = quality
        self.engine = engine
        self.on_close = on_close

    def stream(self, fps: int = 15):
        interval = 1.0 / max(1, min(int(fps), 30))
        next_t = time.time()
        empty_rounds = 0
        try:
            while True:
                img, _meta = render_frame(
                    self.hub, self.camera, annotate=self.annotate, engine=self.engine
                )
                if img is None:
                    empty_rounds += 1
                    if empty_rounds > 3:  # 连续拿不到帧（hub 已停）则结束响应
                        break
                    continue
                empty_rounds = 0
                payload = encode_jpeg(img, self.quality)
                if payload is None:
                    continue
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(payload)).encode()
                    + b"\r\n\r\n"
                    + payload
                    + b"\r\n"
                )
                next_t += interval
                sleep = next_t - time.time()
                if sleep > 0:
                    time.sleep(sleep)
                else:
                    next_t = time.time()
        except (GeneratorExit, StopIteration):
            pass
        except Exception as e:  # pragma: no cover - 防御性收口
            logger.error("视频流异常终止: %s", e)
        finally:
            if self.on_close is not None:
                try:
                    self.on_close()
                except Exception:
                    pass
