"""
image_processor.py v8.1
═════════════════════
- Pill DYNAMIC WIDTH theo text (ngắn=ngắn, dài=dài) - Fix chuẩn textlength
- Pill HEIGHT FIX CỨNG (49px khớp PS)
- Supersampling 4× cho viền nét mịn
- Font picker (chọn family)
- Căn giữa dọc tuyệt đối bằng anchor="lm" (Chống xệ chữ)
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
DEFAULT_BOTTOM_MARGIN = 55
DEFAULT_SIDE_PADDING = 40
DEFAULT_FONT_SIZE = 24.0      # Đã điều chỉnh cho thoáng
DEFAULT_TEXT_PADDING = 25     # Khớp chính xác vạch X=65 trừ X=40

PILL_LEFT      = 40           # TỌA ĐỘ MỚI: Khớp chuẩn vạch guide dọc X=40
PILL_HEIGHT    = 49           # FIX CỨNG: Khớp chuẩn khoảng Y=26 đến Y=75
PILL1_TOP      = 26           # TỌA ĐỘ MỚI: Khớp chuẩn vạch guide ngang Y=26
PILL2_GAP      = 20           # TỌA ĐỘ MỚI: Khớp chuẩn khoảng cách từ Y=75 đến Y=95
MAX_PILL_RIGHT = 580          # pill không vượt quá x=580
MIN_PILL_WIDTH = 100          # pill tối thiểu 100px


# ════ SMART FIT ════
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


# ════ TÁCH NỀN TRẮNG ════
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


# ════ FONT ════
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
    prio = ["Montserrat-ExtraBold","Montserrat-Black","Montserrat-Bold",
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
        if font_family in af: 
            cands.append(af[font_family])
        else:
            cands.append(os.path.join(_font_dir(), f"{font_family}.otf"))
            cands.append(os.path.join(_font_dir(), f"{font_family}.ttf"))
            
    cands.append(os.path.join(_font_dir(), "Montserrat.ttf"))
    cands.append(os.path.join(_font_dir(), "Montserrat.otf"))
    
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


# ════ PILL VỚI SHADOW (supersampled, sắc nét) ════
def draw_pill_with_shadow(canvas, pill_box, shadow_offset=(3,4), shadow_blur=0,
                          shadow_opacity=60, fill_color=(255,255,255)):
    SS = 4
    left, top, right, bottom = pill_box
    w, h = right-left, bottom-top
    radius = h // 2
    sx, sy = shadow_offset
    margin = max(abs(sx), abs(sy)) + 4
    lw, lh = w + margin*2, h + margin*2

    layer = Image.new("RGBA", (lw*SS, lh*SS), (0,0,0,0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle(
        [(margin+sx)*SS, (margin+sy)*SS, (margin+sx+w)*SS, (margin+sy+h)*SS],
        radius=radius*SS, fill=(0,0,0,shadow_opacity))
    d.rounded_rectangle(
        [margin*SS, margin*SS, (margin+w)*SS, (margin+h)*SS],
        radius=radius*SS, fill=(*fill_color, 255))
    layer = layer.resize((lw, lh), Image.LANCZOS)
    canvas.alpha_composite(layer, (left-margin, top-margin))


# ════ ĐO TEXT + AUTO FIT (CHUẨN XÁC) ════
def measure_text_width(text: str, font_size: float, font_weight: int = 700,
                       font_family: Optional[str] = None) -> float:
    """Đo chiều rộng chuẩn xác bằng textlength"""
    if not text: return 0.0
    tmp = Image.new("RGBA", (1,1))
    d = ImageDraw.Draw(tmp)
    f = load_font(font_size, font_weight, font_family)
    return d.textlength(text, font=f)

def calc_dynamic_pill(text: str, font_size: float, font_weight: int,
                      font_family: Optional[str], text_padding: int,
                      pill_left: int, pill_top: int, pill_height: int,
                      max_right: int, min_size: float = 9.0
                      ) -> Tuple[Tuple[int,int,int,int], float]:
    if not text:
        return (pill_left, pill_top, pill_left + MIN_PILL_WIDTH, pill_top + pill_height), font_size

    max_text_w = max_right - pill_left - 2 * text_padding
    size = float(font_size)

    # Shrink text nếu quá dài
    while size >= min_size:
        tw = measure_text_width(text, size, font_weight, font_family)
        if tw <= max_text_w:
            break
        size -= 0.3

    used = max(size, min_size)
    tw = measure_text_width(text, used, font_weight, font_family)

    pill_w = int(tw + 2 * text_padding)
    pill_w = max(pill_w, MIN_PILL_WIDTH)
    pill_right = min(pill_left + pill_w, max_right)

    box = (pill_left, pill_top, pill_right, pill_top + pill_height)
    return box, used

def draw_text_in_pill(canvas, text, pill_box, font_size, font_weight=700,
                      font_family=None, color=(0,0,0), text_padding=26, text_y_nudge=-1):
    """Vẽ text bằng anchor 'lm' để ép tâm dọc tuyệt đối, chống xệ chữ."""
    if not text: return font_size
    draw = ImageDraw.Draw(canvas)
    left, top, right, bottom = pill_box
    f = load_font(font_size, font_weight, font_family)
    
    text_x = left + text_padding
    center_y = top + (bottom - top) / 2
    final_text_y = center_y + text_y_nudge
    
    draw.text((text_x, final_text_y), text, font=f, fill=color, anchor="lm")
    return font_size


# ════ CẤU HÌNH ════
@dataclass
class ThumbnailConfig:
    top_margin: int = DEFAULT_TOP_MARGIN
    bottom_margin: int = DEFAULT_BOTTOM_MARGIN
    side_padding: int = DEFAULT_SIDE_PADDING
    font_size: float = DEFAULT_FONT_SIZE
    font_weight: int = 800
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
    shadow_blur: int = 0
    shadow_opacity: int = 60
    # Font & Nudge
    font_family: Optional[str] = "Montserrat-ExtraBold"
    text_y_nudge: int = -1 # <-- ĐÃ THÊM BIẾN NÀY ĐỂ TRÁNH CRASH


# ════ BUILD THUMBNAIL ════
def build_thumbnail(product_image, text1, text2, background, config):
    W = H = CANVAS_SIZE
    info = {}

    # 1. Background
    if config.show_background:
        bg = background.convert("RGBA").resize((W,H), Image.LANCZOS)
    else:
        bg = Image.new("RGBA", (W,H), (255,255,255,255))

    # 2. Sản phẩm
    prod = product_image.convert("RGBA")
    if config.remove_bg_mode == "white":
        prod = remove_white_background(prod, config.white_tolerance)
    elif config.remove_bg_mode == "ai":
        prod = remove_background_ai(prod)

    area_top = config.top_margin
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
    bg.paste(fitted, (px, py), fitted)

    # 3. Pill + Text (DYNAMIC WIDTH)
    t1 = (text1 or "").strip()
    t2 = (text2 or "").strip()
    sizes_used = []
    sh_off = (config.shadow_offset_x, config.shadow_offset_y)

    if t1:
        pill1, sz1 = calc_dynamic_pill(
            t1, config.font_size, config.font_weight, config.font_family,
            config.text_padding, config.pill_left, config.pill1_top,
            config.pill_height, config.max_pill_right,
        )
        draw_pill_with_shadow(bg, pill1, sh_off, config.shadow_blur, config.shadow_opacity)
        draw_text_in_pill(bg, t1, pill1, sz1, config.font_weight,
                          config.font_family, config.text_color, config.text_padding, config.text_y_nudge)
        sizes_used.append(round(sz1, 2))

    if t2:
        pill2_top = config.pill1_top + config.pill_height + config.pill2_gap
        pill2, sz2 = calc_dynamic_pill(
            t2, config.font_size, config.font_weight, config.font_family,
            config.text_padding, config.pill_left, pill2_top,
            config.pill_height, config.max_pill_right,
        )
        draw_pill_with_shadow(bg, pill2, sh_off, config.shadow_blur, config.shadow_opacity)
        draw_text_in_pill(bg, t2, pill2, sz2, config.font_weight,
                          config.font_family, config.text_color, config.text_padding, config.text_y_nudge)
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
