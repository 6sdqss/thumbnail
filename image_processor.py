"""
image_processor.py
==================
Core engine cho Thumbnail Builder.

Tính năng:
- smart_fit: resize giữ tỉ lệ, không méo, không mất chi tiết
- remove_white_background: tách nền trắng bằng flood-fill (không cần AI)
- remove_background_ai: tách nền bằng rembg (tuỳ chọn)
- draw_pill_with_shadow: tự vẽ ô pill trắng có bóng đổ mềm (không dùng asset khung)
- build_thumbnail: ghép thumbnail 600x600 đúng layout mẫu. Hỗ trợ ô trắng (pill) tự co giãn theo độ dài chữ.
- auto_fit_text: text tự co giãn vừa pill (được giữ lại để tương thích ngược)
"""
from __future__ import annotations

import io
import os
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ============ HẰNG SỐ ============
CANVAS_SIZE = 600
# Layout mặc định mới: sản phẩm nằm ở nửa dưới, pill ở nửa trên (không đè nhau)
DEFAULT_TOP_MARGIN = 155      # đẩy sp xuống dưới pill (pill kết thúc ~y=128 + buffer)
DEFAULT_BOTTOM_MARGIN = 55    # cách đáy, sp không sát viền
DEFAULT_SIDE_PADDING = 40     # cách 2 bên trái/phải
DEFAULT_FONT_SIZE = 20.4
DEFAULT_TEXT_PADDING = 25     # text thụt vào ô pill 25px

# Layout 2 pill - đo chính xác từ thumb mẫu
# Pill left = 8, right = 300 (width ~292), height = 49
# Pill 1: y 8-57 | Pill 2: y 68-117 (gap ~10)
PILL_LEFT = 8
PILL_RIGHT = 300
PILL_HEIGHT = 49
PILL1_TOP = 8
PILL2_TOP = 68  # PILL1_TOP + PILL_HEIGHT + gap


# ============ SMART FIT ============
def _content_bbox(img: Image.Image, alpha_threshold: int = 10) -> Optional[Tuple[int, int, int, int]]:
    if img.mode != "RGBA":
        return img.getbbox()
    alpha = np.array(img.split()[-1])
    mask = alpha > alpha_threshold
    if not mask.any():
        return None
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    return (int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1)


def smart_fit(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize giữ tỉ lệ, crop theo bbox nội dung thực. Không méo, không mất chi tiết."""
    img = img.convert("RGBA")
    bbox = _content_bbox(img)
    if bbox is not None:
        img = img.crop(bbox)

    src_w, src_h = img.size
    if src_w == 0 or src_h == 0:
        return Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))

    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))

    resized = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    canvas.paste(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2), resized)
    return canvas


def smart_fit_centroid(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    Fit và căn giữa theo TRỌNG TÂM (centroid) của khối lượng sản phẩm.

    Khi sản phẩm không đối xứng (VD: chảo có cán lệch lên góc),
    căn theo bbox sẽ làm phần "nặng" (nồi chảo) lệch xuống.
    Căn theo centroid đưa phần "nặng" ra giữa, thị giác cân hơn.

    Cách làm:
      1. Crop theo bbox nội dung.
      2. Tính centroid (cx, cy) dựa trên alpha (hoặc brightness nếu RGB).
      3. Scale giữ tỉ lệ.
      4. Pad thêm vào các cạnh sao cho centroid nằm đúng tâm canvas.
    """
    img = img.convert("RGBA")
    bbox = _content_bbox(img)
    if bbox is not None:
        img = img.crop(bbox)

    src_w, src_h = img.size
    if src_w == 0 or src_h == 0:
        return Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))

    # Tính centroid từ alpha channel
    alpha = np.array(img.split()[-1])
    mass = alpha.astype(np.float32)
    total = mass.sum()
    if total <= 0:
        # Không có alpha có ý nghĩa -> fallback căn giữa bbox
        return smart_fit(img, target_w, target_h)

    ys = np.arange(src_h).reshape(-1, 1)
    xs = np.arange(src_w).reshape(1, -1)
    cx = float((mass * xs).sum() / total)
    cy = float((mass * ys).sum() / total)

    # Scale để ảnh vừa khung
    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    # Centroid sau khi scale
    cx_s = cx * scale
    cy_s = cy * scale

    # Muốn centroid nằm ở tâm canvas
    paste_x = int(round(target_w / 2 - cx_s))
    paste_y = int(round(target_h / 2 - cy_s))

    # Clamp để ảnh không bị cắt khỏi canvas
    min_x = target_w - new_w
    min_y = target_h - new_h
    paste_x = max(min_x, min(0, paste_x)) if new_w >= target_w else max(0, min(target_w - new_w, paste_x))
    paste_y = max(min_y, min(0, paste_y)) if new_h >= target_h else max(0, min(target_h - new_h, paste_y))

    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    canvas.paste(resized, (paste_x, paste_y), resized)
    return canvas


# ============ TÁCH NỀN TRẮNG ============
def _edge_connected(mask: np.ndarray) -> np.ndarray:
    """BFS flood-fill từ 4 cạnh. Chỉ trả về pixel True nối với biên."""
    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    q: deque = deque()
    for x in range(w):
        if mask[0, x]:
            q.append((0, x)); visited[0, x] = True
        if mask[h - 1, x]:
            q.append((h - 1, x)); visited[h - 1, x] = True
    for y in range(h):
        if mask[y, 0]:
            q.append((y, 0)); visited[y, 0] = True
        if mask[y, w - 1]:
            q.append((y, w - 1)); visited[y, w - 1] = True

    while q:
        y, x = q.popleft()
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx] and mask[ny, nx]:
                visited[ny, nx] = True
                q.append((ny, nx))
    return visited


def remove_white_background(img: Image.Image, tolerance: int = 18, feather: int = 1) -> Image.Image:
    """Tách nền trắng bằng flood-fill từ biên. Không ăn vùng trắng bên trong sản phẩm."""
    img = img.convert("RGBA")
    arr = np.array(img)
    rgb = arr[:, :, :3].astype(np.int16)

    min_rgb = rgb.min(axis=2)
    max_rgb = rgb.max(axis=2)
    chroma = max_rgb - min_rgb

    bright_thr = max(180, 255 - tolerance * 4)
    chroma_thr = max(5, tolerance)
    white_mask = (min_rgb >= bright_thr) & (chroma <= chroma_thr)

    edge_mask = _edge_connected(white_mask)
    alpha = arr[:, :, 3].copy()
    alpha[edge_mask] = 0
    arr[:, :, 3] = alpha

    out = Image.fromarray(arr, "RGBA")
    if feather > 0:
        a = out.split()[-1].filter(ImageFilter.GaussianBlur(radius=feather))
        r, g, b, _ = out.split()
        out = Image.merge("RGBA", (r, g, b, a))
    return out


# ============ TÁCH NỀN AI (TUỲ CHỌN) ============
_REMBG_SESSION = None


def remove_background_ai(img: Image.Image) -> Image.Image:
    global _REMBG_SESSION
    try:
        from rembg import new_session, remove
    except ImportError as e:
        raise RuntimeError("Chưa cài rembg. Chạy: pip install rembg onnxruntime") from e

    if _REMBG_SESSION is None:
        _REMBG_SESSION = new_session("u2net")

    img = img.convert("RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out_bytes = remove(buf.getvalue(), session=_REMBG_SESSION)
    return Image.open(io.BytesIO(out_bytes)).convert("RGBA")


# ============ FONT ============
def _font_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


def load_font(size: float, weight: int = 700) -> ImageFont.FreeTypeFont:
    """Load Montserrat variable font. weight: 100-900."""
    size_int = max(1, int(round(size)))
    path = os.path.join(_font_dir(), "Montserrat.ttf")
    candidates = [
        path,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc",
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            try:
                font = ImageFont.truetype(p, size_int)
                if "Montserrat" in p:
                    try:
                        font.set_variation_by_axes([weight])
                    except Exception:
                        pass
                return font
            except Exception:
                continue
    return ImageFont.load_default()


# ============ VẼ PILL VỚI BÓNG ĐỔ ============
def draw_pill_with_shadow(
    canvas: Image.Image,
    pill_box: Tuple[int, int, int, int],
    shadow_offset: Tuple[int, int] = (2, 3),
    shadow_blur: int = 6,
    shadow_opacity: int = 110,
    fill_color: Tuple[int, int, int] = (255, 255, 255),
) -> None:
    """
    Vẽ 1 ô pill trắng bo tròn có bóng đổ mềm phía sau.
    Giống đúng thumb mẫu: pill trắng tinh, shadow xám đổ hơi xuống-phải.
    """
    left, top, right, bottom = pill_box
    w, h = right - left, bottom - top
    radius = h // 2

    # 1. Tạo layer shadow riêng để blur
    pad = shadow_blur * 3
    shadow_layer = Image.new("RGBA", (canvas.width, canvas.height), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_layer)
    sx, sy = shadow_offset
    sd.rounded_rectangle(
        [left + sx, top + sy, right + sx, bottom + sy],
        radius=radius,
        fill=(0, 0, 0, shadow_opacity),
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_blur))

    # 2. Composite shadow
    canvas.alpha_composite(shadow_layer)

    # 3. Vẽ pill trắng lên trên
    pd = ImageDraw.Draw(canvas)
    pd.rounded_rectangle(
        [left, top, right, bottom],
        radius=radius,
        fill=(*fill_color, 255),
    )


# ============ AUTO-FIT TEXT ============
def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1], bbox[1]


def auto_fit_text(
    canvas: Image.Image,
    text: str,
    pill_box: Tuple[int, int, int, int],
    base_size: float = DEFAULT_FONT_SIZE,
    min_size: float = 9.0,
    color: Tuple[int, int, int] = (0, 0, 0),
    weight: int = 700,
    side_padding: int = 22,
) -> float:
    """
    Vẽ text vào pill. (Giữ lại để đảm bảo không lỗi hàm nếu có file khác gọi tới)
    """
    if not text:
        return base_size

    draw = ImageDraw.Draw(canvas)
    left, top, right, bottom = pill_box
    max_w = right - left - 2 * side_padding
    max_h = bottom - top - 4

    size = float(base_size)
    while size >= min_size:
        font = load_font(size, weight)
        tw, th, _ = _measure(draw, text, font)
        if tw <= max_w and th <= max_h:
            break
        size -= 0.3

    used = max(size, min_size)
    font = load_font(used, weight)
    tw, th, y_off = _measure(draw, text, font)

    x = left + side_padding
    pill_h = bottom - top
    # Căn giữa dọc: bù y_off để ký tự nằm chính giữa ô pill
    y = top + (pill_h - th) // 2 - y_off
    draw.text((x, y), text, font=font, fill=color)
    return used


# ============ CẤU HÌNH ============
@dataclass
class ThumbnailConfig:
    top_margin: int = 155
    bottom_margin: int = 55
    side_padding: int = 40
    font_size: float = 20.4
    font_weight: int = 800
    text_color: Tuple[int, int, int] = (0, 0, 0)
    text_padding: int = 25
    remove_bg_mode: str = "none"
    white_tolerance: int = 18
    show_background: bool = True
    center_mode: str = "centroid"
    product_scale: float = 1.0
    pill_left: int = 8
    pill_right: int = 300 # Mặc định cũ, giữ lại để tương thích ngược
    pill_height: int = 49
    pill1_top: int = 8
    pill2_gap: int = 11
    # Thông số bóng đổ đã được tinh chỉnh theo mẫu
    shadow_offset_x: int = 3
    shadow_offset_y: int = 5
    shadow_blur: int = 12  # Tăng để bóng mịn và lan tỏa rộng hơn
    shadow_opacity: int = 85 # Giảm để bóng nhẹ nhàng, không bị đen gắt


# ============ BUILD THUMBNAIL ============
def build_thumbnail(
    product_image: Image.Image,
    text1: str,
    text2: str,
    background: Image.Image,
    config: ThumbnailConfig,
) -> Tuple[Image.Image, dict]:
    """
    Ghép thumbnail 600x600.

    Layer (từ dưới lên):
      1. Background
      2. Sản phẩm (smart-fit + tách nền tuỳ chọn)
      3. Pill shadow + pill trắng + text (1 hoặc 2 pill tự co giãn theo text)

    Trả về (image, info).
    """
    W = H = CANVAS_SIZE
    info: dict = {}

    # 1. Nền
    if config.show_background:
        bg = background.convert("RGBA").resize((W, H), Image.LANCZOS)
    else:
        bg = Image.new("RGBA", (W, H), (255, 255, 255, 255))

    # 2. Sản phẩm
    prod = product_image.convert("RGBA")
    if config.remove_bg_mode == "white":
        prod = remove_white_background(prod, tolerance=config.white_tolerance)
    elif config.remove_bg_mode == "ai":
        prod = remove_background_ai(prod)

    area_top = config.top_margin
    area_bottom = H - config.bottom_margin
    area_h = max(1, area_bottom - area_top)
    area_w = W - 2 * config.side_padding

    # Zoom thủ công: scale > 1 → sp to hơn (có thể vượt area), scale < 1 → nhỏ hơn
    effective_w = max(1, int(area_w * config.product_scale))
    effective_h = max(1, int(area_h * config.product_scale))

    if config.center_mode == "centroid":
        fitted = smart_fit_centroid(prod, effective_w, effective_h)
    else:
        fitted = smart_fit(prod, effective_w, effective_h)

    px = (W - fitted.width) // 2
    py = area_top + (area_h - fitted.height) // 2
    bg.paste(fitted, (px, py), fitted)

    # 3. Pill + text (Tự động co giãn theo chiều dài chữ)
    draw = ImageDraw.Draw(bg)
    font = load_font(config.font_size, config.font_weight)
    
    t1 = (text1 or "").strip()
    t2 = (text2 or "").strip()
    texts = [t1, t2]
    y_positions = [config.pill1_top, config.pill1_top + config.pill_height + config.pill2_gap]
    sizes_used: List[float] = []

    for i, txt in enumerate(texts):
        if not txt:
            continue
            
        # Đo kích thước chữ thực tế
        bbox = draw.textbbox((0, 0), txt, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        y_offset = bbox[1]

        # Tính toán độ rộng ô: lề trái + độ dài chữ + padding 2 bên
        current_pill_width = text_w + (config.text_padding * 2)
        pill_box = (
            config.pill_left, 
            y_positions[i], 
            config.pill_left + current_pill_width, 
            y_positions[i] + config.pill_height
        )

        # Vẽ bóng và ô trắng theo kích thước co giãn
        draw_pill_with_shadow(
            bg, pill_box,
            shadow_offset=(config.shadow_offset_x, config.shadow_offset_y),
            shadow_blur=config.shadow_blur,
            shadow_opacity=config.shadow_opacity
        )

        # Vẽ chữ vào giữa ô (Căn giữa dọc: bù y_offset để ký tự nằm chính giữa ô pill)
        text_x = config.pill_left + config.text_padding
        text_y = y_positions[i] + (config.pill_height - text_h) // 2 - y_offset
        draw.text((text_x, text_y), txt, font=font, fill=config.text_color)
        
        sizes_used.append(config.font_size)

    info["font_sizes_used"] = [round(s, 2) for s in sizes_used]
    info["text1"] = t1
    info["text2"] = t2
    info["any_shrunk"] = False

    return bg.convert("RGB"), info


# ============ TIỆN ÍCH ============
def pil_to_bytes(img: Image.Image, fmt: str = "PNG", quality: int = 95) -> bytes:
    buf = io.BytesIO()
    fmt_u = fmt.upper()
    if fmt_u in ("JPEG", "JPG"):
        img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
    else:
        img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def sanitize_filename(name: str) -> str:
    """Loại bỏ ký tự không hợp lệ cho tên file, giữ unicode."""
    bad = '<>:"/\\|?*\r\n\t'
    out = "".join(c for c in str(name) if c not in bad).strip()
    return out or "unnamed"
