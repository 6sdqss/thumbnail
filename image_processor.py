"""
image_processor.py — Core engine for Thumbnail Builder Pro v8
Pixel-perfect pill layout · Dynamic width · Centroid centering
Khớp 100% Photoshop guides
"""
from __future__ import annotations

import io
import math
import os
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ═══════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════
CANVAS_SIZE = 600

_DIR = Path(__file__).resolve().parent
_FONTS_DIR = _DIR / "fonts"
_FONT_CACHE: Dict[str, ImageFont.FreeTypeFont] = {}
_FONT_MAP: Optional[Dict[str, Path]] = None

# Weight name → wght axis value
_WEIGHT_MAP = {
    "Thin": 100, "ExtraLight": 200, "Light": 300, "Regular": 400,
    "Medium": 500, "SemiBold": 600, "Bold": 700, "ExtraBold": 800,
    "Black": 900,
}


# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════
@dataclass
class ThumbnailConfig:
    # Product placement area
    top_margin: int = 155
    bottom_margin: int = 55
    side_padding: int = 40
    product_scale: float = 1.0
    center_mode: str = "centroid"       # "centroid" | "bbox"

    # Font / text
    font_size: float = 28.5
    font_weight: int = 800
    font_family: str = "Montserrat-ExtraBold"
    text_color: Tuple[int, int, int] = (0, 0, 0)
    text_padding: int = 24             # horizontal padding inside pill

    # Pill geometry (khớp PS guides)
    pill_left: int = 20
    pill_height: int = 49
    pill1_top: int = 15
    pill2_gap: int = 13
    max_pill_right: int = 580

    # Pill shadow
    shadow_offset_x: int = 2
    shadow_offset_y: int = 3
    shadow_blur: int = 0
    shadow_opacity: int = 50

    # Background removal
    remove_bg_mode: str = "none"        # "none" | "white"
    white_tolerance: int = 18
    show_background: bool = True


# ═══════════════════════════════════════════════════════════════
# FONT MANAGEMENT
# ═══════════════════════════════════════════════════════════════
def list_available_fonts() -> Dict[str, Path]:
    """Scan fonts/ directory → dict {display_name: path}."""
    global _FONT_MAP
    if _FONT_MAP is not None:
        return _FONT_MAP

    _FONT_MAP = {}
    if not _FONTS_DIR.is_dir():
        return _FONT_MAP

    for fp in sorted(_FONTS_DIR.glob("*.ttf")):
        stem = fp.stem  # e.g. "Montserrat" or "Montserrat-Italic"
        # Try to enumerate named instances for variable fonts
        try:
            test_font = ImageFont.truetype(str(fp), 20)
            axes = test_font.get_variation_axes()
            has_wght = any(ax["tag"] == "wght" for ax in axes)
            if has_wght:
                # Check for named instances
                try:
                    names = test_font.get_variation_names()
                    if names:
                        for inst in names:
                            n = inst.decode() if isinstance(inst, bytes) else str(inst)
                            key = f"{stem.split('-')[0]}-{n}"
                            _FONT_MAP[key] = fp
                except Exception:
                    pass
                # Also add weight-based entries
                base = stem.split("-")[0]
                for wname in _WEIGHT_MAP:
                    key = f"{base}-{wname}"
                    if key not in _FONT_MAP:
                        _FONT_MAP[key] = fp
            else:
                _FONT_MAP[stem] = fp
        except Exception:
            _FONT_MAP[stem] = fp

    # Always ensure at least the file stems are listed
    for fp in sorted(_FONTS_DIR.glob("*.ttf")):
        if fp.stem not in _FONT_MAP:
            _FONT_MAP[fp.stem] = fp

    return _FONT_MAP


def _resolve_font(family: str, size: float, weight: int = 800) -> ImageFont.FreeTypeFont:
    """Load a font by family name, size, and weight. Caches results."""
    cache_key = f"{family}|{size}|{weight}"
    if cache_key in _FONT_CACHE:
        return _FONT_CACHE[cache_key]

    font_path = None
    available = list_available_fonts()

    # Direct match
    if family in available:
        font_path = available[family]
    else:
        # Fuzzy: try base name + weight
        for name, fp in available.items():
            if family.lower().replace("-", "") in name.lower().replace("-", ""):
                font_path = fp
                break
        # Last resort: first available
        if font_path is None and available:
            font_path = next(iter(available.values()))

    # Load font
    if font_path and font_path.exists():
        try:
            font = ImageFont.truetype(str(font_path), int(round(size)))
            # Try setting variable weight
            try:
                axes = font.get_variation_axes()
                has_wght = any(ax["tag"] == "wght" for ax in axes)
                if has_wght:
                    # Try named instance first
                    wname = None
                    for n, v in _WEIGHT_MAP.items():
                        if v == weight:
                            wname = n
                            break
                    set_ok = False
                    if wname:
                        try:
                            font.set_variation_by_name(wname)
                            set_ok = True
                        except Exception:
                            pass
                    if not set_ok:
                        try:
                            # Build axis values list
                            axis_vals = []
                            for ax in axes:
                                if ax["tag"] == "wght":
                                    clamped = max(ax["minimum"], min(ax["maximum"], weight))
                                    axis_vals.append(clamped)
                                else:
                                    axis_vals.append(ax["default"])
                            font.set_variation_by_axes(axis_vals)
                        except Exception:
                            pass
            except Exception:
                pass  # Not a variable font

            _FONT_CACHE[cache_key] = font
            return font
        except Exception:
            pass

    # System fallback
    for fallback in ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "arial.ttf"]:
        try:
            font = ImageFont.truetype(fallback, int(round(size)))
            _FONT_CACHE[cache_key] = font
            return font
        except Exception:
            continue

    font = ImageFont.load_default()
    _FONT_CACHE[cache_key] = font
    return font


# ═══════════════════════════════════════════════════════════════
# TEXT MEASUREMENT
# ═══════════════════════════════════════════════════════════════
def measure_text_width(text: str, font_size: float,
                       font_family: str = "Montserrat-ExtraBold",
                       font_weight: int = 800) -> float:
    """Measure rendered text width in pixels."""
    if not text:
        return 0.0
    font = _resolve_font(font_family, font_size, font_weight)
    bbox = font.getbbox(text)
    return float(bbox[2] - bbox[0])


def _fit_text(text: str, max_width: float, start_size: float,
              font_family: str, font_weight: int,
              min_size: float = 9.0) -> Tuple[float, bool]:
    """Find font size that fits text within max_width.
    Returns (final_size, was_shrunk)."""
    if not text:
        return start_size, False

    sz = start_size
    w = measure_text_width(text, sz, font_family, font_weight)
    if w <= max_width:
        return sz, False

    # Binary search for best fit
    lo, hi = min_size, start_size
    while hi - lo > 0.25:
        mid = (lo + hi) / 2
        if measure_text_width(text, mid, font_family, font_weight) <= max_width:
            lo = mid
        else:
            hi = mid
    return lo, True


# ═══════════════════════════════════════════════════════════════
# PILL DRAWING
# ═══════════════════════════════════════════════════════════════
def _draw_pill(canvas: Image.Image, text: str, x: int, y: int,
               cfg: ThumbnailConfig, font_size_override: float = None) -> float:
    """Draw a single white pill with text and shadow. Returns actual font size used."""
    if not text.strip():
        return 0.0

    fs = font_size_override if font_size_override else cfg.font_size
    font = _resolve_font(cfg.font_family, fs, cfg.font_weight)

    # Measure text
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    # Pill dimensions
    pill_w = int(tw + cfg.text_padding * 2)
    pill_h = cfg.pill_height
    radius = pill_h // 2  # Full capsule

    # Clamp width
    max_w = cfg.max_pill_right - x
    if pill_w > max_w:
        pill_w = max_w

    # ── Shadow layer ──
    if cfg.shadow_opacity > 0:
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sx = x + cfg.shadow_offset_x
        sy = y + cfg.shadow_offset_y
        sd.rounded_rectangle(
            [sx, sy, sx + pill_w, sy + pill_h],
            radius=radius,
            fill=(0, 0, 0, cfg.shadow_opacity),
        )
        if cfg.shadow_blur > 0:
            shadow = shadow.filter(ImageFilter.GaussianBlur(cfg.shadow_blur))
        canvas.alpha_composite(shadow)

    # ── White pill ──
    pill = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    pd = ImageDraw.Draw(pill)
    pd.rounded_rectangle(
        [x, y, x + pill_w, y + pill_h],
        radius=radius,
        fill=(255, 255, 255, 255),
    )
    canvas.alpha_composite(pill)

    # ── Text ──
    txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(txt_layer)

    # Vertical center: align text midline to pill midline
    text_y = y + (pill_h - th) // 2 - bbox[1]  # compensate for font ascent offset
    text_x = x + cfg.text_padding

    td.text(
        (text_x, text_y),
        text,
        font=font,
        fill=(*cfg.text_color, 255),
    )
    canvas.alpha_composite(txt_layer)

    return fs


# ═══════════════════════════════════════════════════════════════
# WHITE BACKGROUND REMOVAL (flood-fill from edges)
# ═══════════════════════════════════════════════════════════════
def _remove_white_bg(img: Image.Image, tolerance: int = 18) -> Image.Image:
    """Remove white-ish background via edge flood-fill."""
    img = img.convert("RGBA")
    arr = np.array(img)
    h, w = arr.shape[:2]

    # Mask: True where pixel is "white enough"
    rgb = arr[:, :, :3].astype(np.int16)
    is_white = np.all(rgb >= (255 - tolerance), axis=2)

    # BFS flood-fill from all edge pixels that are white
    visited = np.zeros((h, w), dtype=bool)
    queue = deque()

    # Seed from edges
    for x in range(w):
        for y_edge in (0, h - 1):
            if is_white[y_edge, x] and not visited[y_edge, x]:
                visited[y_edge, x] = True
                queue.append((y_edge, x))
    for y in range(h):
        for x_edge in (0, w - 1):
            if is_white[y, x_edge] and not visited[y, x_edge]:
                visited[y, x_edge] = True
                queue.append((y, x_edge))

    while queue:
        cy, cx = queue.popleft()
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny, nx = cy + dy, cx + dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx] and is_white[ny, nx]:
                visited[ny, nx] = True
                queue.append((ny, nx))

    # Set visited (background) pixels to transparent
    arr[visited, 3] = 0

    # Feather edges: 1px blur on alpha channel for cleaner cutout
    alpha_img = Image.fromarray(arr[:, :, 3], "L")
    alpha_img = alpha_img.filter(ImageFilter.SMOOTH)
    arr[:, :, 3] = np.array(alpha_img)

    return Image.fromarray(arr, "RGBA")


# ═══════════════════════════════════════════════════════════════
# PRODUCT IMAGE PROCESSING
# ═══════════════════════════════════════════════════════════════
def _get_content_bbox(img: Image.Image) -> Tuple[int, int, int, int]:
    """Get bounding box of non-transparent content."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    alpha = np.array(img)[:, :, 3]
    rows = np.any(alpha > 10, axis=1)
    cols = np.any(alpha > 10, axis=0)
    if not rows.any() or not cols.any():
        return (0, 0, img.width, img.height)
    y0, y1 = np.where(rows)[0][[0, -1]]
    x0, x1 = np.where(cols)[0][[0, -1]]
    return (int(x0), int(y0), int(x1 + 1), int(y1 + 1))


def _get_centroid(img: Image.Image) -> Tuple[float, float]:
    """Get alpha-weighted centroid of image content."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    alpha = np.array(img)[:, :, 3].astype(np.float64)
    total = alpha.sum()
    if total < 1:
        return (img.width / 2, img.height / 2)
    ys, xs = np.mgrid[:img.height, :img.width]
    cx = float((xs * alpha).sum() / total)
    cy = float((ys * alpha).sum() / total)
    return (cx, cy)


def _fit_product(product: Image.Image, cfg: ThumbnailConfig) -> Image.Image:
    """Process, resize, and center product onto a transparent CANVAS_SIZE layer."""
    prod = product.convert("RGBA")

    # ── Remove background ──
    if cfg.remove_bg_mode == "white":
        prod = _remove_white_bg(prod, cfg.white_tolerance)

    # ── Crop to content ──
    bbox = _get_content_bbox(prod)
    prod = prod.crop(bbox)
    if prod.width < 1 or prod.height < 1:
        return Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))

    # ── Available area ──
    avail_w = CANVAS_SIZE - cfg.side_padding * 2
    avail_h = CANVAS_SIZE - cfg.top_margin - cfg.bottom_margin

    # ── Scale to fit ──
    scale = min(avail_w / prod.width, avail_h / prod.height) * cfg.product_scale
    new_w = max(1, int(prod.width * scale))
    new_h = max(1, int(prod.height * scale))
    prod = prod.resize((new_w, new_h), Image.LANCZOS)

    # ── Position on canvas ──
    layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))

    # Target center of available area
    area_cx = CANVAS_SIZE / 2
    area_cy = cfg.top_margin + avail_h / 2

    if cfg.center_mode == "centroid":
        # Align centroid of product to area center
        cx, cy = _get_centroid(prod)
        paste_x = int(area_cx - cx)
        paste_y = int(area_cy - cy)
    else:
        # BBox center
        paste_x = int(area_cx - new_w / 2)
        paste_y = int(area_cy - new_h / 2)

    # Clamp to canvas bounds
    paste_x = max(0, min(CANVAS_SIZE - new_w, paste_x))
    paste_y = max(0, min(CANVAS_SIZE - new_h, paste_y))

    layer.paste(prod, (paste_x, paste_y), prod)
    return layer


# ═══════════════════════════════════════════════════════════════
# MAIN BUILD FUNCTION
# ═══════════════════════════════════════════════════════════════
def build_thumbnail(
    product_img: Image.Image,
    text1: str,
    text2: str,
    background: Image.Image,
    cfg: ThumbnailConfig,
) -> Tuple[Image.Image, dict]:
    """
    Build a complete 600×600 thumbnail.

    Returns:
        (thumbnail_image, info_dict)
        info_dict keys: font_sizes_used, any_shrunk
    """
    # ── Canvas base ──
    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (255, 255, 255, 255))

    # ── Background ──
    if cfg.show_background and background:
        bg = background.convert("RGBA")
        if bg.size != (CANVAS_SIZE, CANVAS_SIZE):
            bg = bg.resize((CANVAS_SIZE, CANVAS_SIZE), Image.LANCZOS)
        canvas.alpha_composite(bg)

    # ── Product layer ──
    prod_layer = _fit_product(product_img, cfg)
    canvas.alpha_composite(prod_layer)

    # ── Text pills ──
    max_pill_w = cfg.max_pill_right - cfg.pill_left - cfg.text_padding * 2
    font_sizes_used = []
    any_shrunk = False

    t1 = text1.strip().upper() if text1 else ""
    t2 = text2.strip().upper() if text2 else ""

    # Pill 1
    if t1:
        fs1, shrunk1 = _fit_text(t1, max_pill_w, cfg.font_size,
                                  cfg.font_family, cfg.font_weight)
        actual_fs1 = _draw_pill(canvas, t1, cfg.pill_left, cfg.pill1_top, cfg, fs1)
        font_sizes_used.append(round(fs1, 1))
        if shrunk1:
            any_shrunk = True

    # Pill 2
    if t2:
        pill2_top = cfg.pill1_top + cfg.pill_height + cfg.pill2_gap
        fs2, shrunk2 = _fit_text(t2, max_pill_w, cfg.font_size,
                                  cfg.font_family, cfg.font_weight)
        actual_fs2 = _draw_pill(canvas, t2, cfg.pill_left, pill2_top, cfg, fs2)
        font_sizes_used.append(round(fs2, 1))
        if shrunk2:
            any_shrunk = True

    info = {
        "font_sizes_used": font_sizes_used,
        "any_shrunk": any_shrunk,
    }
    return canvas, info


# ═══════════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════════
def pil_to_bytes(img: Image.Image, fmt: str = "png", quality: int = 92) -> bytes:
    """Convert PIL Image to bytes in requested format."""
    buf = io.BytesIO()
    fmt_lower = fmt.lower().strip(".")

    if fmt_lower in ("jpg", "jpeg"):
        out = img.convert("RGB") if img.mode == "RGBA" else img
        out.save(buf, "JPEG", quality=quality, optimize=True)
    elif fmt_lower == "webp":
        img.save(buf, "WEBP", quality=quality, method=4)
    else:
        img.save(buf, "PNG", optimize=True)

    return buf.getvalue()


def sanitize_filename(name: str) -> str:
    """Remove unsafe characters from filename."""
    safe = re.sub(r'[^\w\-.]', '_', str(name).strip())
    safe = re.sub(r'_+', '_', safe).strip('_')
    return safe or "unnamed"
