"""
image_processor.py v10
══════════════════════
Nâng cấp từ v9:
  Fix #8: Tracking -28 — vẽ từng ký tự với letter-spacing khớp PS
  Fix #9: Font size 32.0 (PS 24pt × 96/72 = 32px Pillow)
  
Giữ nguyên v9: white canvas, product shadow, pill SS4×, auto top_margin,
               bottom gradient, dynamic pill width, centroid centering.
"""
from __future__ import annotations

import io
import os
import urllib.request
import tempfile
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ════ HẰNG SỐ ════
CANVAS_SIZE = 600
DEFAULT_TOP_MARGIN = 155
DEFAULT_BOTTOM_MARGIN = 35
DEFAULT_SIDE_PADDING = 40

# Fix #9: PS 24pt × (96DPI / 72DPI) = 32px Pillow
DEFAULT_FONT_SIZE = 28.5
DEFAULT_TEXT_PADDING = 31.5     # khớp PS X=46 - pill_left=20

# Fix #8: PS Tracking -28 (đơn vị 1/1000 em)
DEFAULT_TRACKING = -48

PILL_LEFT      = 20
PILL_HEIGHT    = 49           # FIX CỨNG từ asset gốc
PILL1_TOP      = 14           # từ asset gốc
PILL2_GAP      = 14           # 78-64 = 14 (từ asset)
MAX_PILL_RIGHT = 520          # pill không vượt quá x=520
MIN_PILL_WIDTH = 100          # pill tối thiểu 100px


# ════ SMART FIT (giữ nguyên v8) ════
def _content_bbox(img, alpha_threshold=10):
    if img.mode != "RGBA": return img.getbbox()
    alpha = np.array(img.split()[-1])
    mask = alpha > alpha_threshold
    if not mask.any(): return None
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    return (int(cols.min()), int(rows.min()), int(cols.max())+1, int(rows.max())+1)

def smart_fit(img, target_w, target_h):
    img = img.convert("RGBA")
    bbox = _content_bbox(img)
    if bbox: img = img.crop(bbox)
    sw, sh = img.size
    if sw == 0 or sh == 0: return Image.new("RGBA", (target_w, target_h), (0,0,0,0))
    scale = min(target_w / sw, target_h / sh)
    nw, nh = max(1, int(round(sw*scale))), max(1, int(round(sh*scale)))
    resized = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (target_w, target_h), (0,0,0,0))
    canvas.paste(resized, ((target_w-nw)//2, (target_h-nh)//2), resized)
    return canvas

def smart_fit_centroid(img, target_w, target_h):
    img = img.convert("RGBA")
    bbox = _content_bbox(img)
    if bbox: img = img.crop(bbox)
    sw, sh = img.size
    if sw == 0 or sh == 0: return Image.new("RGBA", (target_w, target_h), (0,0,0,0))
    alpha = np.array(img.split()[-1]).astype(np.float32)
    total = alpha.sum()
    if total <= 0: return smart_fit(img, target_w, target_h)
    cx = float((alpha * np.arange(sw).reshape(1,-1)).sum() / total)
    cy = float((alpha * np.arange(sh).reshape(-1,1)).sum() / total)
    scale = min(target_w / sw, target_h / sh)
    nw, nh = max(1, int(round(sw*scale))), max(1, int(round(sh*scale)))
    resized = img.resize((nw, nh), Image.LANCZOS)
    px = int(round(target_w/2 - cx*scale))
    py = int(round(target_h/2 - cy*scale))
    px = max(0, min(target_w-nw, px)) if nw < target_w else max(target_w-nw, min(0, px))
    py = max(0, min(target_h-nh, py)) if nh < target_h else max(target_h-nh, min(0, py))
    canvas = Image.new("RGBA", (target_w, target_h), (0,0,0,0))
    canvas.paste(resized, (px, py), resized)
    return canvas


# ════ TÁCH NỀN TRẮNG (giữ nguyên v8) ════
def _edge_connected(mask):
    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    q = deque()
    for x in range(w):
        if mask[0,x]: q.append((0,x)); visited[0,x]=True
        if mask[h-1,x]: q.append((h-1,x)); visited[h-1,x]=True
    for y in range(h):
        if mask[y,0]: q.append((y,0)); visited[y,0]=True
        if mask[y,w-1]: q.append((y,w-1)); visited[y,w-1]=True
    while q:
        y,x = q.popleft()
        for dy,dx in ((-1,0),(1,0),(0,-1),(0,1)):
            ny,nx = y+dy, x+dx
            if 0<=ny<h and 0<=nx<w and not visited[ny,nx] and mask[ny,nx]:
                visited[ny,nx]=True; q.append((ny,nx))
    return visited

def remove_white_background(img, tolerance=18, feather=1):
    img = img.convert("RGBA"); arr = np.array(img)
    rgb = arr[:,:,:3].astype(np.int16)
    min_rgb, max_rgb = rgb.min(axis=2), rgb.max(axis=2)
    chroma = max_rgb - min_rgb
    white_mask = (min_rgb >= max(180, 255-tolerance*4)) & (chroma <= max(5, tolerance))
    edge = _edge_connected(white_mask)
    arr[:,:,3][edge] = 0
    out = Image.fromarray(arr, "RGBA")
    if feather > 0:
        a = out.split()[-1].filter(ImageFilter.GaussianBlur(feather))
        out = Image.merge("RGBA", (*out.split()[:3], a))
    return out

def remove_background_ai(img):
    global _REMBG_SESSION
    try:
        from rembg import new_session, remove
    except ImportError as e:
        raise RuntimeError("rembg chưa cài") from e
    if '_REMBG_SESSION' not in globals() or _REMBG_SESSION is None:
        _REMBG_SESSION = new_session("u2net")
    img = img.convert("RGBA"); buf = io.BytesIO(); img.save(buf, "PNG")
    return Image.open(io.BytesIO(remove(buf.getvalue(), session=_REMBG_SESSION))).convert("RGBA")

_REMBG_SESSION = None


# ════ FONT (giữ nguyên v8) ════
def _font_dir(): return os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

_FONT_CACHE: dict = {}

def _download_montserrat():
    cache = os.path.join(tempfile.gettempdir(), "Montserrat.ttf")
    if os.path.isfile(cache) and os.path.getsize(cache) > 100_000: return cache
    for url in [
        "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
        "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf",
    ]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r: data = r.read()
            if len(data) > 100_000:
                with open(cache, "wb") as f: f.write(data)
                return cache
        except Exception: continue
    return None

def list_available_fonts() -> Dict[str, str]:
    fd = _font_dir(); fonts = {}
    if os.path.isdir(fd):
        for fn in sorted(os.listdir(fd)):
            if not fn.lower().endswith((".ttf",".otf")): continue
            if "italic" in fn.lower() or fn.lower().startswith("ofl"): continue
            name = os.path.splitext(fn)[0].replace("-VariableFont_wght","")
            fonts[name] = os.path.join(fd, fn)
    prio = ["Montserrat-Bold","Montserrat-Black",
            "MontserratAlternates-Black","MontserratAlternates-ExtraBold",
            "MontserratAlternates-Bold","MontserratAlternates-Medium",
            "MontserratAlternates-Regular","Montserrat"]
    ordered = {}
    for k in prio:
        if k in fonts: ordered[k] = fonts.pop(k)
    ordered.update(fonts)
    return ordered

def load_font(size: float, weight: int = 700, font_family: Optional[str] = None) -> ImageFont.FreeTypeFont:
    sz = max(1, int(round(size)))
    key = (sz, weight, font_family or "__def__")
    if key in _FONT_CACHE: return _FONT_CACHE[key]
    cands = []
    if font_family:
        af = list_available_fonts()
        if font_family in af: cands.append(af[font_family])
    cands.append(os.path.join(_font_dir(), "Montserrat.ttf"))
    dl = _download_montserrat()
    if dl: cands.append(dl)
    cands += ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
              "C:/Windows/Fonts/arialbd.ttf"]
    for p in cands:
        if p and os.path.isfile(p):
            try:
                f = ImageFont.truetype(p, sz)
                if "Montserrat.ttf" in p and not font_family:
                    try: f.set_variation_by_axes([weight])
                    except: pass
                _FONT_CACHE[key] = f; return f
            except: continue
    f = ImageFont.load_default(); _FONT_CACHE[key] = f; return f


# ════ Fix #8: TRACKED TEXT — vẽ từng ký tự với letter-spacing ════
def _tracking_px(font_size: float, tracking_em: int) -> float:
    """Chuyển PS tracking (1/1000 em) sang pixel offset.
    VD: tracking=-28, font=32px → -28/1000 × 32 = -0.896px/ký tự"""
    return tracking_em / 1000.0 * font_size

def _measure_width_tracked(text: str, font: ImageFont.FreeTypeFont,
                           font_size: float, tracking_em: int) -> float:
    """Đo chiều rộng text CÓ tracking (char-by-char).
    Giống cách PS tính width với VA=-28."""
    if not text:
        return 0.0
    if len(text) == 1 or tracking_em == 0:
        return font.getlength(text)
    tk = _tracking_px(font_size, tracking_em)
    total = 0.0
    for i, ch in enumerate(text):
        total += font.getlength(ch)
        if i < len(text) - 1:
            total += tk
    return total

def _draw_text_tracked(draw: ImageDraw.ImageDraw, x: float, y: float,
                       text: str, font: ImageFont.FreeTypeFont,
                       font_size: float, fill, tracking_em: int):
    """Vẽ text từng ký tự với tracking offset (giãn chữ).
    Nếu tracking=0 → vẽ nguyên khối như bình thường."""
    if not text:
        return
    if tracking_em == 0:
        draw.text((x, y), text, font=font, fill=fill, anchor="lm")
        return
    tk = _tracking_px(font_size, tracking_em)
    cx = float(x)
    for i, ch in enumerate(text):
        draw.text((cx, y), ch, font=font, fill=fill, anchor="lm")
        cx += font.getlength(ch)
        if i < len(text) - 1:
            cx += tk


# ════ PILL VỚI SHADOW — Fix #3 ════
def draw_pill_with_shadow(canvas, pill_box, shadow_offset=(3,4), shadow_blur=5,
                          shadow_opacity=90, fill_color=(255,255,255)):
    """Vẽ pill + shadow. Supersampling 4× cho viền nét."""
    SS = 4
    left, top, right, bottom = pill_box
    w, h = right-left, bottom-top
    radius = h // 2
    sx, sy = shadow_offset

    blur_extra = (shadow_blur + 2) if shadow_blur > 0 else 0
    margin = max(abs(sx), abs(sy)) + blur_extra + 4
    lw, lh = w + margin*2, h + margin*2

    layer = Image.new("RGBA", (lw*SS, lh*SS), (0,0,0,0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle(
        [(margin+sx)*SS, (margin+sy)*SS, (margin+sx+w)*SS, (margin+sy+h)*SS],
        radius=radius*SS, fill=(0,0,0,shadow_opacity))

    if shadow_blur > 0:
        layer = layer.filter(ImageFilter.GaussianBlur(shadow_blur * SS))

    d2 = ImageDraw.Draw(layer)
    d2.rounded_rectangle(
        [margin*SS, margin*SS, (margin+w)*SS, (margin+h)*SS],
        radius=radius*SS, fill=(*fill_color, 255))

    layer = layer.resize((lw, lh), Image.LANCZOS)
    canvas.alpha_composite(layer, (left-margin, top-margin))


# ════ PILL + TEXT — pill SS4×, text 1× với tracking ════
def draw_pill_and_text_ss(canvas, text, pill_box, font_size, font_weight=700,
                          font_family=None, text_color=(0,0,0), text_padding=24,
                          shadow_offset=(2,3), shadow_blur=0, shadow_opacity=50,
                          fill_color=(255,255,255), tracking=-28, text_y_nudge=0):
    """
    Pill supersampled 4× cho viền mịn.
    Text vẽ 1× từng ký tự với tracking (Fix #8).
    """
    # ─── PHẦN 1: VẼ PILL SUPERSAMPLED ───
    SS = 4
    left, top, right, bottom = pill_box
    w, h = right-left, bottom-top
    radius = h // 2
    sx, sy = shadow_offset

    blur_extra = (shadow_blur + 2) if shadow_blur > 0 else 0
    margin = max(abs(sx), abs(sy)) + blur_extra + 4
    lw, lh = w + margin*2, h + margin*2

    layer = Image.new("RGBA", (lw*SS, lh*SS), (0,0,0,0))
    d = ImageDraw.Draw(layer)

    # Bóng
    d.rounded_rectangle(
        [(margin+sx)*SS, (margin+sy)*SS, (margin+sx+w)*SS, (margin+sy+h)*SS],
        radius=radius*SS, fill=(0,0,0,shadow_opacity))

    if shadow_blur > 0:
        layer = layer.filter(ImageFilter.GaussianBlur(shadow_blur * SS))

    # Pill trắng
    d2 = ImageDraw.Draw(layer)
    d2.rounded_rectangle(
        [margin*SS, margin*SS, (margin+w)*SS, (margin+h)*SS],
        radius=radius*SS, fill=(*fill_color, 255))

    # Downscale pill → dán lên canvas
    layer = layer.resize((lw, lh), Image.LANCZOS)
    canvas.alpha_composite(layer, (left-margin, top-margin))

    # ─── PHẦN 2: VẼ TEXT 1× VỚI TRACKING (Fix #8) ───
    if text:
        draw = ImageDraw.Draw(canvas)
        f = load_font(font_size, font_weight, font_family)
        
        x = left + text_padding
        center_y = top + (h / 2) + text_y_nudge
        
        # Vẽ từng ký tự với tracking
        _draw_text_tracked(draw, x, center_y, text, f, font_size, text_color, tracking)

    return font_size


# ════ (giữ lại cho backward compat) ════
def draw_text_in_pill(canvas, text, pill_box, font_size, font_weight=700,
                      font_family=None, color=(0,0,0), text_padding=26):
    """Vẽ text căn trái + căn giữa dọc trong pill_box. (Legacy v8)"""
    if not text: return font_size
    draw = ImageDraw.Draw(canvas)
    left, top, right, bottom = pill_box
    f = load_font(font_size, font_weight, font_family)
    tw, th, y_off = _measure(draw, text, f)
    x = left + text_padding
    y = top + (bottom - top - th) // 2 - y_off
    draw.text((x, y), text, font=f, fill=color)
    return font_size


# ════ Fix #2: BÓNG SẢN PHẨM ════
def draw_product_shadow(canvas, fitted_img, paste_x, paste_y,
                        canvas_w, canvas_h, opacity=28, blur_radius=12):
    """Vẽ bóng elip mờ dưới chân sản phẩm (DMX style)."""
    bbox = _content_bbox(fitted_img)
    if not bbox:
        return

    content_left, content_top, content_right, content_bottom = bbox
    abs_bottom = paste_y + content_bottom
    abs_center_x = paste_x + (content_left + content_right) // 2
    content_w = content_right - content_left

    shadow_half_w = max(60, int(content_w * 0.38))
    shadow_half_h = max(10, int(content_w * 0.04))
    shadow_y = min(abs_bottom + 2, canvas_h - 15)

    layer = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([
        abs_center_x - shadow_half_w, shadow_y - shadow_half_h,
        abs_center_x + shadow_half_w, shadow_y + shadow_half_h,
    ], fill=(0, 0, 0, opacity))

    layer = layer.filter(ImageFilter.GaussianBlur(blur_radius))
    canvas.alpha_composite(layer)


# ════ Fix #6: GRADIENT ĐÁY ════
def apply_bottom_gradient(canvas, start_ratio=0.78, darken_amount=0.07):
    """Gradient nhẹ đáy canvas (DMX floor effect)."""
    w, h = canvas.size
    start_y = int(h * start_ratio)
    gradient_h = h - start_y
    if gradient_h <= 0:
        return
    arr = np.array(canvas, dtype=np.float32)
    t = np.linspace(0, 1, gradient_h).reshape(-1, 1, 1)
    arr[start_y:, :, :3] *= (1.0 - darken_amount * t)
    canvas.paste(Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA"))


# ════ ĐO TEXT + AUTO FIT ════
def _measure(draw, text, font):
    bbox = draw.textbbox((0,0), text, font=font)
    return bbox[2]-bbox[0], bbox[3]-bbox[1], bbox[1]

def measure_text_width(text: str, font_size: float, font_weight: int = 700,
                       font_family: Optional[str] = None,
                       tracking: int = 0) -> Tuple[float, float]:
    """Đo chiều rộng và cao text CÓ tracking. Dùng để tính pill width."""
    if not text: return (0, 0)
    f = load_font(font_size, font_weight, font_family)
    # Height: dùng _measure gốc (tracking không ảnh hưởng chiều cao)
    tmp = Image.new("RGBA", (1,1))
    d = ImageDraw.Draw(tmp)
    _, th, _ = _measure(d, text, f)
    # Width: có tracking
    tw = _measure_width_tracked(text, f, font_size, tracking)
    return (tw, th)

def calc_dynamic_pill(text: str, font_size: float, font_weight: int,
                      font_family: Optional[str], text_padding: int,
                      pill_left: int, pill_top: int, pill_height: int,
                      max_right: int, min_size: float = 9.0,
                      tracking: int = 0
                      ) -> Tuple[Tuple[int,int,int,int], float]:
    """
    Tính pill_box DYNAMIC WIDTH dựa theo text CÓ tracking.
    Returns: (pill_box, font_size_used)
    """
    if not text:
        pw = MIN_PILL_WIDTH
        return (pill_left, pill_top, pill_left + pw, pill_top + pill_height), font_size

    max_text_w = max_right - pill_left - 2 * text_padding
    size = float(font_size)

    while size >= min_size:
        tw, th = measure_text_width(text, size, font_weight, font_family, tracking)
        if tw <= max_text_w and th <= pill_height - 4:
            break
        size -= 0.3

    used = max(size, min_size)
    tw, _ = measure_text_width(text, used, font_weight, font_family, tracking)

    pill_w = int(tw + 2 * text_padding)
    pill_w = max(pill_w, MIN_PILL_WIDTH)
    pill_right = min(pill_left + pill_w, max_right)

    box = (pill_left, pill_top, pill_right, pill_top + pill_height)
    return box, used


# ════ CẤU HÌNH ════
@dataclass
class ThumbnailConfig:
    top_margin: int = DEFAULT_TOP_MARGIN
    bottom_margin: int = DEFAULT_BOTTOM_MARGIN
    side_padding: int = DEFAULT_SIDE_PADDING
    font_size: float = DEFAULT_FONT_SIZE
    font_weight: int = 700
    text_color: Tuple[int,int,int] = (0,0,0)
    text_padding: int = DEFAULT_TEXT_PADDING
    remove_bg_mode: str = "none"
    white_tolerance: int = 18
    show_background: bool = True
    center_mode: str = "centroid"
    product_scale: float = 1.0
    # Pill layout
    pill_left: int = PILL_LEFT
    pill_height: int = PILL_HEIGHT
    pill1_top: int = PILL1_TOP
    pill2_gap: int = PILL2_GAP
    max_pill_right: int = MAX_PILL_RIGHT
    # Shadow
    shadow_offset_x: int = 3
    shadow_offset_y: int = 4
    shadow_blur: int = 5
    shadow_opacity: int = 90
    # Font family
    font_family: Optional[str] = None
    # Fix #8: Tracking (PS VA, đơn vị 1/1000 em, mặc định -28)
    tracking: int = DEFAULT_TRACKING
    # Text Y Nudge
    text_y_nudge: int = 0
    # Fix #2: bóng sản phẩm
    product_shadow: bool = True
    product_shadow_opacity: int = 28
    product_shadow_blur: int = 12
    # Fix #6: gradient đáy
    bottom_gradient: bool = False
    bottom_gradient_strength: float = 0.07


# ════ BUILD THUMBNAIL ════
def build_thumbnail(product_image, text1, text2, background, config):
    W = H = CANVAS_SIZE
    info = {}

    # ── Fix #1: Canvas TRẮNG ──
    bg = Image.new("RGBA", (W, H), (255, 255, 255, 255))

    if config.show_background:
        bg_layer = background.convert("RGBA").resize((W, H), Image.LANCZOS)
        bg.alpha_composite(bg_layer)

    # ── Fix #6: Gradient đáy ──
    if config.bottom_gradient:
        apply_bottom_gradient(bg, darken_amount=config.bottom_gradient_strength)

    # ── Fix #5: Auto top_margin ──
    t1 = (text1 or "").strip()
    t2 = (text2 or "").strip()

    pill_area_bottom = 0
    if t1:
        pill_area_bottom = config.pill1_top + config.pill_height
    if t2:
        pill_area_bottom = config.pill1_top + config.pill_height + config.pill2_gap + config.pill_height

    min_top = pill_area_bottom + 20 if pill_area_bottom > 0 else 0
    effective_top = max(config.top_margin, min_top)

    # ── Sản phẩm ──
    prod = product_image.convert("RGBA")
    if config.remove_bg_mode == "white":
        prod = remove_white_background(prod, config.white_tolerance)
    elif config.remove_bg_mode == "ai":
        prod = remove_background_ai(prod)

    area_top = effective_top
    area_h = max(1, H - config.bottom_margin - area_top)
    area_w = W - 2 * config.side_padding
    ew = max(1, int(area_w * config.product_scale))
    eh = max(1, int(area_h * config.product_scale))

    if config.center_mode == "centroid":
        fitted = smart_fit_centroid(prod, ew, eh)
    else:
        fitted = smart_fit(prod, ew, eh)

    px = (W - fitted.width) // 2
    py = area_top + (area_h - fitted.height) // 2

    # ── Fix #2: Bóng sản phẩm ──
    if config.product_shadow:
        draw_product_shadow(bg, fitted, px, py, W, H,
                            opacity=config.product_shadow_opacity,
                            blur_radius=config.product_shadow_blur)

    bg.paste(fitted, (px, py), fitted)

    # ── Pill + Text — với tracking ──
    sizes_used = []
    sh_off = (config.shadow_offset_x, config.shadow_offset_y)
    tk = config.tracking
    nudge = config.text_y_nudge

    if t1:
        pill1, sz1 = calc_dynamic_pill(
            t1, config.font_size, config.font_weight, config.font_family,
            config.text_padding, config.pill_left, config.pill1_top,
            config.pill_height, config.max_pill_right, tracking=tk,
        )
        draw_pill_and_text_ss(
            bg, t1, pill1, sz1, config.font_weight,
            config.font_family, config.text_color, config.text_padding,
            sh_off, config.shadow_blur, config.shadow_opacity,
            tracking=tk, text_y_nudge=nudge
        )
        sizes_used.append(round(sz1, 2))

    if t2:
        pill2_top = config.pill1_top + config.pill_height + config.pill2_gap
        pill2, sz2 = calc_dynamic_pill(
            t2, config.font_size, config.font_weight, config.font_family,
            config.text_padding, config.pill_left, pill2_top,
            config.pill_height, config.max_pill_right, tracking=tk,
        )
        draw_pill_and_text_ss(
            bg, t2, pill2, sz2, config.font_weight,
            config.font_family, config.text_color, config.text_padding,
            sh_off, config.shadow_blur, config.shadow_opacity,
            tracking=tk, text_y_nudge=nudge
        )
        sizes_used.append(round(sz2, 2))

    info["font_sizes_used"] = sizes_used
    info["text1"] = t1
    info["text2"] = t2
    info["any_shrunk"] = any(s < config.font_size - 0.01 for s in sizes_used)

    return bg.convert("RGB"), info


# ════ TIỆN ÍCH ════
def pil_to_bytes(img, fmt="PNG", quality=95):
    buf = io.BytesIO()
    if fmt.upper() in ("JPEG","JPG"):
        img.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
    elif fmt.upper() == "WEBP":
        img.save(buf, "WEBP", quality=quality)
    else:
        img.save(buf, "PNG", optimize=True)
    return buf.getvalue()

def sanitize_filename(name):
    return "".join(c for c in str(name) if c not in '<>:"/\\|?*\r\n\t').strip() or "unnamed"
