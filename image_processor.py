"""
image_processor.py
==================
Core engine cho Thumbnail Builder.

Tính năng:
- smart_fit: resize giữ tỉ lệ, không méo, không mất chi tiết
- remove_white_background: tách nền trắng bằng flood-fill (không cần AI)
- remove_background_ai: tách nền bằng rembg (tuỳ chọn)
- draw_pill_with_shadow: tự vẽ ô pill trắng có bóng đổ mềm (không dùng asset khung)
- build_thumbnail: ghép thumbnail 600x600 đúng layout mẫu
- auto_fit_text: text tự co giãn vừa pill
"""
from __future__ import annotations

import io
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ============ HẰNG SỐ ============
CANVAS_SIZE = 600
# Layout mặc định mới: sản phẩm nằm ở nửa dưới, pill ở nửa trên (không đè nhau)
DEFAULT_TOP_MARGIN = 155      # đẩy sp xuống dưới pill (pill kết thúc ~y=128 + buffer)
DEFAULT_BOTTOM_MARGIN = 35    # cách đáy, sp không sát viền
DEFAULT_SIDE_PADDING = 40     # cách 2 bên trái/phải
DEFAULT_FONT_SIZE = 35
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


_FONT_CACHE: dict = {}


def _download_montserrat_if_needed() -> Optional[str]:
    """
    Nếu không có font local, tự download Montserrat từ Google Fonts GitHub mirror.
    Lưu vào /tmp/Montserrat.ttf để dùng lại.
    Trả về path đến file font, hoặc None nếu thất bại.
    """
    import tempfile
    import urllib.request

    cache_path = os.path.join(tempfile.gettempdir(), "Montserrat.ttf")
    if os.path.isfile(cache_path) and os.path.getsize(cache_path) > 100_000:
        return cache_path

    urls = [
        "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
        "https://github.com/JulietaUla/Montserrat/raw/master/fonts/variable/Montserrat%5Bwght%5D.ttf",
        "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            if len(data) > 100_000:
                with open(cache_path, "wb") as f:
                    f.write(data)
                return cache_path
        except Exception:
            continue
    return None


def list_available_fonts() -> Dict[str, str]:
    """
    Scan folder fonts/ và trả về dict {display_name: file_path} của tất cả font có sẵn.

    Ưu tiên các font phổ biến cho thumbnail:
      - Montserrat-Black (đậm nhất, giống mẫu)
      - Montserrat-ExtraBold
      - Montserrat-Bold
      - MontserratAlternates-Black (có chữ 'a' dạng round, đẹp cho thương hiệu)
      - v.v.
    """
    font_dir = _font_dir()
    fonts: Dict[str, str] = {}

    if os.path.isdir(font_dir):
        for fn in sorted(os.listdir(font_dir)):
            if not fn.lower().endswith((".ttf", ".otf")): continue
            if fn.lower().startswith("ofl"): continue
            name = os.path.splitext(fn)[0]
            # Loại bỏ các file Italic (ít dùng cho thumbnail)
            if "italic" in name.lower(): continue
            # Loại bỏ VariableFont tag
            name = name.replace("-VariableFont_wght", "").replace("VariableFont_wght", "")
            fonts[name] = os.path.join(font_dir, fn)

    # Thứ tự ưu tiên hiển thị (đậm → nhạt, alternates trước nếu có)
    priority = [
        "MontserratAlternates-Black", "MontserratAlternates-ExtraBold", "MontserratAlternates-Bold",
        "MontserratAlternates-Medium", "MontserratAlternates-Regular",
        "Montserrat-Black", "Montserrat-Bold", "Montserrat",
    ]
    ordered = {}
    for k in priority:
        if k in fonts: ordered[k] = fonts.pop(k)
    ordered.update(fonts)  # thêm các font còn lại
    return ordered


def load_font(
    size: float,
    weight: int = 700,
    font_family: Optional[str] = None,
) -> ImageFont.FreeTypeFont:
    """
    Load font với kích thước + (tuỳ chọn) tên family cụ thể.

    Args:
      size: kích thước font
      weight: chỉ dùng cho variable font Montserrat.ttf (100-900)
      font_family: tên file font KHÔNG có đuôi, VD "Montserrat-Black" hoặc
                   "MontserratAlternates-ExtraBold". Nếu None → dùng
                   Montserrat variable mặc định.

    Caching trong _FONT_CACHE.
    """
    size_int = max(1, int(round(size)))
    cache_key = (size_int, weight, font_family or "__default__")
    if cache_key in _FONT_CACHE:
        return _FONT_CACHE[cache_key]

    candidates: List[str] = []

    # Nếu user chọn font family cụ thể → ưu tiên nó
    if font_family:
        available = list_available_fonts()
        if font_family in available:
            candidates.append(available[font_family])
        else:
            # Sửa lỗi: Nếu không tìm thấy trong dict, thử ghép đuôi .otf hoặc .ttf
            font_path_otf = os.path.join(_font_dir(), f"{font_family}.otf")
            font_path_ttf = os.path.join(_font_dir(), f"{font_family}.ttf")
            candidates.append(font_path_otf)
            candidates.append(font_path_ttf)

    # Fallback: Montserrat variable
    candidates.append(os.path.join(_font_dir(), "Montserrat.ttf"))
    candidates.append(os.path.join(_font_dir(), "Montserrat.otf")) # Thêm dòng này để backup

    # Download nếu thiếu
    downloaded = _download_montserrat_if_needed()
    if downloaded:
        candidates.append(downloaded)

    # Fallback hệ thống
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

    for p in candidates:
        if p and os.path.isfile(p):
            try:
                font = ImageFont.truetype(p, size_int)
                # Chỉ variable font mới cần set_variation_by_axes
                if "Montserrat.ttf" in p and not font_family:
                    try: font.set_variation_by_axes([weight])
                    except Exception: pass
                _FONT_CACHE[cache_key] = font
                return font
            except Exception:
                continue

    font = ImageFont.load_default()
    _FONT_CACHE[cache_key] = font
    return font


# ============ BACKGROUND FALLBACK ============
def generate_default_background(size: int = 600) -> Image.Image:
    """
    Tự vẽ background giống mẫu bằng code:
    - Nền trắng có gradient xám rất nhẹ
    - Đường chân trời (shadow mềm) để sản phẩm "đứng" trên bề mặt

    Dùng khi không có file background.png.
    """
    bg = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    arr = np.array(bg).astype(np.float32)

    # Gradient nhẹ: tối hơn ở 2 mép trái/phải (tạo cảm giác sâu)
    xs = np.linspace(-1.0, 1.0, size)
    vignette = 1.0 - 0.04 * (xs ** 2)  # giảm nhẹ về 2 bên
    for c in range(3):
        arr[:, :, c] *= vignette[None, :]

    # Đường chân trời: ~75% chiều cao có shadow mờ
    horizon_y = int(size * 0.78)
    shadow_strip = np.linspace(1.0, 0.93, size - horizon_y)
    for c in range(3):
        arr[horizon_y:, :, c] *= shadow_strip[:, None]

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    bg = Image.fromarray(arr, "RGBA")

    # Shadow elip mờ ở giữa dưới (như ảnh studio)
    shadow_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_layer)
    cx, cy = size // 2, int(size * 0.82)
    rw, rh = int(size * 0.35), int(size * 0.04)
    sd.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill=(0, 0, 0, 35))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=8))
    bg.alpha_composite(shadow_layer)

    return bg


# ============ VẼ PILL VỚI BÓNG ĐỔ ============
def draw_pill_with_shadow(
    canvas: Image.Image,
    pill_box: Tuple[int, int, int, int],
    shadow_offset: Tuple[int, int] = (3, 4),
    shadow_blur: int = 0,
    shadow_opacity: int = 85,
    fill_color: Tuple[int, int, int] = (255, 255, 255),
) -> None:
    """
    Vẽ ô pill trắng + duplicate pill xám phía sau (SẮC NÉT như mẫu Photoshop).

    Kỹ thuật:
      - Vẽ pill + shadow pill ở kích thước 4× → downscale LANCZOS về 1×
      - KHÔNG blur → viền sắc nét, không bị vỡ
      - Shadow pill offset chính xác 3-4px xuống-phải
      - Downsample bằng LANCZOS = anti-alias chuẩn nhất (không blur)
    """
    SS = 4  # supersample factor — viền mịn không răng cưa

    left, top, right, bottom = pill_box
    w, h = right - left, bottom - top
    radius = h // 2

    sx, sy = shadow_offset

    # ═══ COMPOSITE LAYER: vẽ cả shadow + pill chính ở supersample ═══
    # Bao gồm cả vùng offset shadow
    margin = max(abs(sx), abs(sy)) + 4
    layer_w = w + margin * 2
    layer_h = h + margin * 2

    layer_ss = Image.new("RGBA", (layer_w * SS, layer_h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer_ss)

    # 1. Vẽ SHADOW PILL (duplicate, dịch xuống-phải) ở supersample
    d.rounded_rectangle(
        [(margin + sx) * SS, (margin + sy) * SS,
         (margin + sx + w) * SS, (margin + sy + h) * SS],
        radius=radius * SS,
        fill=(0, 0, 0, shadow_opacity),
    )

    # 2. Vẽ PILL TRẮNG đè lên (tại vị trí gốc)
    d.rounded_rectangle(
        [margin * SS, margin * SS,
         (margin + w) * SS, (margin + h) * SS],
        radius=radius * SS,
        fill=(*fill_color, 255),
    )

    # Downscale LANCZOS → anti-alias mịn mà vẫn SẮC NÉT (không blur)
    layer_final = layer_ss.resize((layer_w, layer_h), Image.LANCZOS)

    # Paste vào canvas tại đúng vị trí pill_box
    canvas.alpha_composite(layer_final, (left - margin, top - margin))


# ============ VẼ KHUNG VÀ CHỮ (FIX CHIỀU CAO, DÃN CHIỀU DÀI) ============
def draw_dynamic_pill_and_text(
    canvas: Image.Image,
    text: str,
    y_top: int,
    config: ThumbnailConfig
) -> float:
    if not text:
        return config.font_size

    draw = ImageDraw.Draw(canvas)
    
    # Ép dùng size chuẩn, không tự động thu nhỏ font nữa để đảm bảo đồng nhất
    font = load_font(config.font_size, config.font_weight, config.font_family)
    
    # 1. FIX HỘP CHỨA: Thay textbbox bằng textlength để đo chiều ngang cực chuẩn
    text_width = draw.textlength(text, font=font)
    
    # 2. Tính chiều dài khung (Pill): Chiều ngang thực tế của chữ + Padding 2 bên
    actual_pill_width = int(text_width) + (config.text_padding * 2)
    actual_pill_right = min(config.pill_left + actual_pill_width, config.pill_right)
    
    # Khóa cứng chiều cao (y_top đến y_top + pill_height)
    pill_box = (
        config.pill_left,
        y_top,
        actual_pill_right,
        y_top + config.pill_height
    )

    # 3. Vẽ Khung trắng và Bóng đổ
    draw_pill_with_shadow(
        canvas, pill_box,
        shadow_offset=(config.shadow_offset_x, config.shadow_offset_y),
        shadow_blur=config.shadow_blur,
        shadow_opacity=config.shadow_opacity,
    )

    # 4. Vẽ Chữ (Ép căn giữa tuyệt đối theo trục Y bằng anchor "lm")
    text_x = config.pill_left + config.text_padding
    
    # Tìm tọa độ tâm của khung trắng
    center_y = y_top + (config.pill_height / 2)
    
    # Sử dụng text_y_nudge để đẩy chữ lên xuống cho vừa mắt nhất
    final_text_y = center_y + config.text_y_nudge
    
    # Dùng anchor "lm" (Left-Middle) để Pillow tự động bám tâm Y
    draw.text((text_x, final_text_y), text, font=font, fill=config.text_color, anchor="lm")
    
    return config.font_size


# ============ CẤU HÌNH ============
@dataclass
class ThumbnailConfig:
    top_margin: int = DEFAULT_TOP_MARGIN           # 155: sp dưới pill
    bottom_margin: int = DEFAULT_BOTTOM_MARGIN     # 55: không sát đáy
    side_padding: int = DEFAULT_SIDE_PADDING       # 40: không sát viền trái/phải
    font_size: float = DEFAULT_FONT_SIZE
    font_weight: int = 700                         # ĐỔI TỪ 800 -> 900 (BLACK) ĐỂ CHỮ CỨNG CÁP HƠN
    text_color: Tuple[int, int, int] = (51, 51, 51) # ĐỔI TỪ ĐEN -> XÁM ĐẬM (#333333) ĐỂ MÀU NHẸ HƠN
    text_padding: int = DEFAULT_TEXT_PADDING       # 25: text thụt 25px
    remove_bg_mode: str = "none"                   # "none" | "white" | "ai"
    white_tolerance: int = 18
    show_background: bool = True
    center_mode: str = "centroid"                  # "bbox" | "centroid"
    product_scale: float = 1.0                     # zoom thủ công (0.5-1.3)
    # Layout 2 pill
    pill_left: int = PILL_LEFT
    pill_right: int = PILL_RIGHT
    pill_height: int = PILL_HEIGHT
    pill1_top: int = PILL1_TOP
    pill2_gap: int = 11
    # Shadow
    shadow_offset_x: int = 1                      # ĐỔI TỪ 2 -> 1 ĐỂ GIẢM CẢM GIÁC LƠ LỬNG
    shadow_offset_y: int = 2                      # ĐỔI TỪ 3 -> 2 ĐỂ GIẢM CẢM GIÁC LƠ LỬNG
    shadow_blur: int = 6
    shadow_opacity: int = 40                      # ĐỔI TỪ 110 -> 40 (BÓNG RẤT NHẸ ĐỂ GIỮ SỰ SẮC NÉT VÀ CHẮC CHẮN)
    # Font family (None = dùng Montserrat variable mặc định)
    font_family: Optional[str] = None
    text_y_nudge: int = -2  # <--- THÊM DÒNG NÀY VÀO DƯỚI CÙNG


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
      3. Pill shadow + pill trắng + text (1 hoặc 2 pill)

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

    # 3. Pill + text (Dynamic Width)
    t1 = (text1 or "").strip()
    t2 = (text2 or "").strip()

    sizes_used: List[float] = []

    if t1:
        s = draw_dynamic_pill_and_text(bg, t1, config.pill1_top, config)
        sizes_used.append(s)

    if t2:
        pill2_top = config.pill1_top + config.pill_height + config.pill2_gap
        s = draw_dynamic_pill_and_text(bg, t2, pill2_top, config)
        sizes_used.append(s)

    info["font_sizes_used"] = [round(s, 2) for s in sizes_used]
    info["text1"] = t1
    info["text2"] = t2
    info["any_shrunk"] = any(s < config.font_size - 0.01 for s in sizes_used)

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
