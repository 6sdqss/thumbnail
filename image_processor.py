"""
image_processor.py
==================
Core engine cho Thumbnail Builder.

Tính năng:
- smart_fit: resize giữ tỉ lệ, không méo, không mất chi tiết
- remove_white_background: tách nền trắng bằng flood-fill (không cần AI)
- remove_background_ai: tách nền bằng rembg (tuỳ chọn)
- draw_pill_with_shadow: tự vẽ ô pill trắng có bóng đổ mềm (Fix lỗi răng cưa bằng Oversampling)
- build_thumbnail: ghép thumbnail 600x600 đúng layout mẫu.
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
DEFAULT_TOP_MARGIN = 155      
DEFAULT_BOTTOM_MARGIN = 55    
DEFAULT_SIDE_PADDING = 40     
DEFAULT_FONT_SIZE = 20.4
DEFAULT_TEXT_PADDING = 25     

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
    img = img.convert("RGBA")
    bbox = _content_bbox(img)
    if bbox is not None:
        img = img.crop(bbox)

    src_w, src_h = img.size
    if src_w == 0 or src_h == 0:
        return Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))

    alpha = np.array(img.split()[-1])
    mass = alpha.astype(np.float32)
    total = mass.sum()
    if total <= 0:
        return smart_fit(img, target_w, target_h)

    ys = np.arange(src_h).reshape(-1, 1)
    xs = np.arange(src_w).reshape(1, -1)
    cx = float((mass * xs).sum() / total)
    cy = float((mass * ys).sum() / total)

    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    cx_s = cx * scale
    cy_s = cy * scale

    paste_x = int(round(target_w / 2 - cx_s))
    paste_y = int(round(target_h / 2 - cy_s))

    min_x = target_w - new_w
    min_y = target_h - new_h
    paste_x = max(min_x, min(0, paste_x)) if new_w >= target_w else max(0, min(target_w - new_w, paste_x))
    paste_y = max(min_y, min(0, paste_y)) if new_h >= target_h else max(0, min(target_h - new_h, paste_y))

    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    canvas.paste(resized, (paste_x, paste_y), resized)
    return canvas

# ============ TÁCH NỀN TRẮNG ============
def _edge_connected(mask: np.ndarray) -> np.ndarray:
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

# ============ TÁCH NỀN AI ============
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

# ============ VẼ PILL (ANTI-ALIASING) ============
def draw_pill_with_shadow(
    canvas: Image.Image,
    pill_box: Tuple[int, int, int, int],
    shadow_offset: Tuple[int, int] = (3, 5),
    shadow_blur: int = 5,
    shadow_opacity: int = 112,
    fill_color: Tuple[int, int, int] = (255, 255, 255),
) -> None:
    """
    Sử dụng Alpha Masking (4x) kết hợp Lanczos để viền bo cong mượt tuyệt đối,
    khử 100% răng cưa của Pillow.
    """
    left, top, right, bottom = pill_box
    w, h = right - left, bottom - top
    radius = h // 2

    # 1. Layer bóng đổ (không cần khử răng cưa vì dùng GaussianBlur)
    shadow_layer = Image.new("RGBA", (canvas.width, canvas.height), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_layer)
    sx, sy = shadow_offset
    sd.rounded_rectangle(
        [left + sx, top + sy, right + sx, bottom + sy],
        radius=radius,
        fill=(0, 0, 0, shadow_opacity),
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_blur))
    canvas.alpha_composite(shadow_layer)

    # 2. Khử răng cưa tuyệt đối cho viền ô Pill bằng Alpha Masking (4x)
    scale = 4
    mask_w, mask_h = w * scale, h * scale
    
    # Vẽ một mặt nạ (Mask) trắng đen to gấp 4 lần
    mask_hr = Image.new("L", (mask_w, mask_h), 0)
    md = ImageDraw.Draw(mask_hr)
    md.rounded_rectangle([0, 0, mask_w, mask_h], radius=radius * scale, fill=255)
    
    # Thu nhỏ mặt nạ bằng Lanczos để lấy phần viền siêu mượt
    mask_lr = mask_hr.resize((w, h), Image.LANCZOS)
    
    # Tạo ô Pill đúng màu và áp mặt nạ mượt vào kênh Alpha
    pill_layer = Image.new("RGBA", (w, h), (*fill_color, 255))
    pill_layer.putalpha(mask_lr)
    
    # Dán ô Pill hoàn hảo lên canvas (dùng chính nó làm mask để hoà trộn đúng)
    canvas.paste(pill_layer, (left, top), pill_layer)

# ============ CẤU HÌNH CỨNG THEO YÊU CẦU ============
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
    pill_left: int = 20    # Update cứng từ ảnh (20)
    pill_right: int = 300
    pill_height: int = 49
    pill1_top: int = 8
    pill2_gap: int = 11
    # Bóng đổ update theo ảnh
    shadow_offset_x: int = 3
    shadow_offset_y: int = 5
    shadow_blur: int = 5
    shadow_opacity: int = 112


# ============ BUILD THUMBNAIL ============
def build_thumbnail(
    product_image: Image.Image,
    text1: str,
    text2: str,
    background: Image.Image,
    config: ThumbnailConfig,
) -> Tuple[Image.Image, dict]:
    W = H = CANVAS_SIZE
    info: dict = {}

    # 1. Chuẩn bị hình nền
    if config.show_background:
        bg = background.convert("RGBA").resize((W, H), Image.LANCZOS)
    else:
        bg = Image.new("RGBA", (W, H), (255, 255, 255, 255))

    # 2. Xử lý ảnh sản phẩm (Tách nền, Căn giữa, Zoom)
    prod = product_image.convert("RGBA")
    if config.remove_bg_mode == "white":
        prod = remove_white_background(prod, tolerance=config.white_tolerance)
    elif config.remove_bg_mode == "ai":
        prod = remove_background_ai(prod)

    area_top = config.top_margin
    area_bottom = H - config.bottom_margin
    area_h = max(1, area_bottom - area_top)
    area_w = W - 2 * config.side_padding

    effective_w = max(1, int(area_w * config.product_scale))
    effective_h = max(1, int(area_h * config.product_scale))

    if config.center_mode == "centroid":
        fitted = smart_fit_centroid(prod, effective_w, effective_h)
    else:
        fitted = smart_fit(prod, effective_w, effective_h)

    px = (W - fitted.width) // 2
    py = area_top + (area_h - fitted.height) // 2
    bg.paste(fitted, (px, py), fitted)

    # 3. Chuẩn bị vẽ Text và Pill
    draw = ImageDraw.Draw(bg)
    font = load_font(config.font_size, config.font_weight)
    
    t1 = (text1 or "").strip()
    t2 = (text2 or "").strip()
    texts = [t1, t2]
    y_positions = [config.pill1_top, config.pill1_top + config.pill_height + config.pill2_gap]
    sizes_used: List[float] = []

    # === ĐÂY LÀ VÒNG LẶP QUAN TRỌNG ĐÃ ĐƯỢC CHỈNH SỬA ===
    for i, txt in enumerate(texts):
        if not txt:
            continue
            
        # A. Đo kích thước của chữ để tính toán độ rộng ô trắng
        bbox = draw.textbbox((0, 0), txt, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        y_offset = bbox[1]

        # B. Tính toạ độ khung ô trắng (Pill Box)
        current_pill_width = text_w + (config.text_padding * 2)
        pill_box = (
            config.pill_left, 
            y_positions[i], 
            config.pill_left + current_pill_width, 
            y_positions[i] + config.pill_height
        )

        # C. VẼ Ô TRẮNG BO GÓC SIÊU MƯỢT TRƯỚC (Dùng Alpha Masking)
        draw_pill_with_shadow(
            canvas=bg,
            pill_box=pill_box,
            shadow_offset=(config.shadow_offset_x, config.shadow_offset_y),
            shadow_blur=config.shadow_blur,
            shadow_opacity=config.shadow_opacity
        )

        # D. VẼ CHỮ ĐÈ LÊN TRÊN Ô TRẮNG (Canh giữa tuyệt đối)
        text_x = config.pill_left + config.text_padding
        text_y = y_positions[i] + (config.pill_height - text_h) // 2 - y_offset
        draw.text((text_x, text_y), txt, font=font, fill=config.text_color)
        
        sizes_used.append(config.font_size)

    # 4. Đóng gói thông tin xuất ra
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
    bad = '<>:"/\\|?*\r\n\t'
    out = "".join(c for c in str(name) if c not in bad).strip()
    return out or "unnamed"
