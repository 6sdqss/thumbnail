"""
app.py — Thumbnail Builder Pro v7 (Production)
════════════════════════════════════════════════
Tối ưu cho xử lý hàng loạt 100+ SP/ngày, không lỗi, UI nhất quán.

TÍNH NĂNG:
  ✓ Tự nén ảnh upload (tiết kiệm RAM 5-7x)
  ✓ Validation panel - kiểm tra all trước khi xuất
  ✓ Chỉnh TẤT CẢ hoặc TỪNG TẤM riêng lẻ
  ✓ Sao chép cấu hình giữa các SP
  ✓ Xuất nhiều size cùng lúc (600, 300, 800...)
  ✓ Lưu/Tải cấu hình ra file JSON
  ✓ Preset theo loại SP
  ✓ Export PNG / JPG / WebP
  ✓ Bulk edit text trong bảng
  ✓ Xử lý lỗi triệt để - không crash
"""
from __future__ import annotations
import io, json, time, zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFilter, UnidentifiedImageError
from image_processor import (
    CANVAS_SIZE, ThumbnailConfig, build_thumbnail,
    pil_to_bytes, sanitize_filename,
)
from auth import require_login, logout_btn


# ══════════════════════════════════════════════════════
# HẰNG SỐ — đã tối ưu khớp mẫu
# ══════════════════════════════════════════════════════
PILL_LEFT     = 20
PILL_RIGHT    = 600    
PILL_HEIGHT   = 49     
PILL1_TOP     = 14
PILL2_GAP     = 14
SHADOW_X      = 2
SHADOW_Y      = 3      # Rớt bóng xuống 3px cho sắc sảo
SHADOW_BLUR   = 0
SHADOW_OP     = 55     # Bóng màu xám vừa, không quá gắt
TEXT_PADDING  = 22     # Lề 2 bên của chữ để có độ thoáng giống gốc
FONT_WEIGHT   = 800    # Chuẩn Montserrat-Bold
TEXT_Y_NUDGE  = -3     # Kéo chữ lên 1 tí xíu cho ngay tâm tuyệt đối
WHITE_TOL     = 18
DEFAULT_FONT_FAMILY = "Montserrat-Bold" # Chốt dùng Bold

MAX_UPLOAD_DIM = 1600
MAX_UPLOAD_MB  = 20
MIN_SRC_DIM    = 400
SUPPORTED_SIZES = [300, 600, 800, 1000, 1200]

APP_VERSION = "7.0"


# ══════════════════════════════════════════════════════
# FALLBACK BG
# ══════════════════════════════════════════════════════
def _fallback_bg(sz=600):
    bg = Image.new("RGBA", (sz, sz), (255, 255, 255, 255))
    a = np.array(bg, dtype=np.float32)
    h = int(sz * .78)
    for c in range(3): a[h:, :, c] *= np.linspace(1, .93, sz - h)[:, None]
    bg = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")
    s = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    ImageDraw.Draw(s).ellipse(
        [sz//2-210, int(sz*.82)-24, sz//2+210, int(sz*.82)+24], fill=(0, 0, 0, 35)
    )
    bg.alpha_composite(s.filter(ImageFilter.GaussianBlur(8)))
    return bg


# ══════════════════════════════════════════════════════
# PAGE
# ══════════════════════════════════════════════════════
st.set_page_config(page_title="Thumbnail Builder Pro", page_icon="🖼️",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
  .block-container{padding-top:4.5rem !important; max-width:1500px;}
  #MainMenu, footer{visibility:hidden;}
  .hero-title{
    background:linear-gradient(135deg,#667eea,#764ba2,#f093fb);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
    font-size:30px; font-weight:900; letter-spacing:-0.8px; margin:0;
  }
  .stButton>button{border-radius:10px !important; font-weight:600 !important;}
  .stButton>button[kind="primary"]{
    background:linear-gradient(135deg,#667eea,#764ba2) !important; border:none !important;
  }
  .stDownloadButton>button{
    border-radius:10px !important; font-weight:700 !important;
    background:linear-gradient(135deg,#10b981,#059669) !important;
    color:#fff !important; border:none !important;
  }
  .stTabs [data-baseweb="tab-list"]{gap:4px;}
  .stTabs [data-baseweb="tab"]{font-weight:700; font-size:13px; padding:10px 18px;}
  section[data-testid="stSidebar"]{background:#fafbfd;}
  [data-testid="stMetric"]{
    background:#fff; border:1px solid #e5e7eb; border-radius:12px;
    padding:14px 18px; box-shadow:0 1px 3px rgba(0,0,0,.04);
  }
  [data-testid="stMetricValue"]{font-size:26px !important; font-weight:800 !important;}
  [data-testid="stFileUploader"] section{
    border:2px dashed #c7d2fe !important; background:#faf5ff !important; border-radius:12px !important;
  }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════════════
if not require_login():
    st.stop()


# ══════════════════════════════════════════════════════
# PATHS
# ══════════════════════════════════════════════════════
_DIR = Path(__file__).resolve().parent
_ASSETS = _DIR / "assets"


@st.cache_resource(show_spinner=False)
def _bg():
    p = _ASSETS / "background.png"
    if p.exists():
        try: return Image.open(p).convert("RGBA")
        except Exception: pass
    return _fallback_bg()


# ══════════════════════════════════════════════════════
# PRESETS
# ══════════════════════════════════════════════════════
PRESETS: Dict[str, dict] = {
    "🎯 Chuẩn (mặc định)": dict(top_margin=175, bottom_margin=35, side_padding=40,
                                product_scale=1.0, center_mode="centroid", font_size=35.0),
    "🍳 Đồ gia dụng": dict(top_margin=185, bottom_margin=50, side_padding=50,
                           product_scale=1.1, center_mode="centroid", font_size=32.0),
    "🎧 Điện tử": dict(top_margin=180, bottom_margin=60, side_padding=40,
                       product_scale=1.0, center_mode="centroid", font_size=32.0),
    "🧴 Mỹ phẩm, chai": dict(top_margin=175, bottom_margin=55, side_padding=60,
                             product_scale=0.95, center_mode="bbox", font_size=32.0),
    "👕 Thời trang": dict(top_margin=175, bottom_margin=45, side_padding=35,
                          product_scale=1.05, center_mode="bbox", font_size=32.0),
    "📱 Điện thoại dọc": dict(top_margin=180, bottom_margin=50, side_padding=70,
                              product_scale=1.0, center_mode="bbox", font_size=32.0),
}


# ══════════════════════════════════════════════════════
# STATE
# ══════════════════════════════════════════════════════
def _init_state():
    st.session_state.setdefault("preset_name", "🎯 Chuẩn (mặc định)")
    st.session_state.setdefault("overrides", {})
    for k, v in PRESETS[st.session_state["preset_name"]].items():
        st.session_state.setdefault(f"cfg_{k}", v)

_init_state()


def _apply_preset(name: str):
    if name not in PRESETS: return
    for k, v in PRESETS[name].items():
        st.session_state[f"cfg_{k}"] = v
    st.session_state["preset_name"] = name


# ══════════════════════════════════════════════════════
# HELPERS (nén, đọc file)
# ══════════════════════════════════════════════════════
def _compress_upload(data: bytes, max_dim: int = MAX_UPLOAD_DIM) -> bytes:
    """Nén ảnh upload để tiết kiệm RAM (không đụng chất lượng thumbnail 600×600)."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return data
    w, h = img.size
    if max(w, h) <= max_dim:
        return data
    scale = max_dim / max(w, h)
    img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    # Giữ PNG nếu có alpha, nếu không dùng JPEG cho gọn
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img.save(buf, "PNG", optimize=True)
    else:
        img.convert("RGB").save(buf, "JPEG", quality=95, optimize=True)
    return buf.getvalue()


def _read_excel(file) -> pd.DataFrame:
    name = getattr(file, "name", "").lower()
    df = (pd.read_csv(file, dtype=str, keep_default_na=False) if name.endswith(".csv")
          else pd.read_excel(file, dtype=str, keep_default_na=False))
    df.columns = [str(c).strip().lower().replace(" ", "") for c in df.columns]
    m = {}
    for c in df.columns:
        if c in ("id","sku","masp","ma","productid","code"): m[c] = "id"
        elif c in ("text1","tt1","dong1","line1","title1"): m[c] = "text1"
        elif c in ("text2","tt2","dong2","line2","title2"): m[c] = "text2"
    df = df.rename(columns=m)
    for col in ("id","text1","text2"):
        if col not in df.columns: df[col] = ""
    df = df[["id","text1","text2"]].copy()
    for col in df.columns: df[col] = df[col].astype(str).str.strip()
    return df[df["id"] != ""].reset_index(drop=True)


def _match(df, imgs):
    by_stem: Dict[str, Tuple[bytes, str]] = {}
    for f in imgs:
        stem = Path(f.name).stem.strip().lower()
        try:
            raw = f.getvalue()
            compressed = _compress_upload(raw)
            by_stem[stem] = (compressed, f.name)
        except Exception:
            continue
    mapping, names, ok, miss = {}, {}, [], []
    for pid in df["id"].tolist():
        k = str(pid).strip().lower()
        hit = by_stem.get(k)
        if not hit:
            for s, d in by_stem.items():
                if k in s or s in k: hit = d; break
        if hit:
            mapping[pid] = hit[0]; names[pid] = hit[1]; ok.append(pid)
        else:
            miss.append(pid)
    return mapping, names, ok, miss


def _effective_df() -> pd.DataFrame:
    """df với text overrides áp dụng."""
    df = st.session_state.get("df")
    if df is None: return pd.DataFrame()
    df = df.copy()
    ov = st.session_state.get("overrides", {})
    for pid, o in ov.items():
        mask = df["id"] == pid
        if o.get("t1") is not None: df.loc[mask, "text1"] = o["t1"]
        if o.get("t2") is not None: df.loc[mask, "text2"] = o["t2"]
    return df


def _build_config_for(pid: Optional[str] = None) -> ThumbnailConfig:
    g = {
        "top_margin": st.session_state.get("cfg_top_margin", 155),
        "bottom_margin": st.session_state.get("cfg_bottom_margin", 55),
        "side_padding": st.session_state.get("cfg_side_padding", 40),
        "product_scale": st.session_state.get("cfg_product_scale", 1.0),
        "center_mode": st.session_state.get("cfg_center_mode", "centroid"),
        "font_size": st.session_state.get("cfg_font_size", 20.4),
    }
    ov = st.session_state.get("overrides", {}).get(pid or "", {})
    for k in g:
        if ov.get(k) is not None: g[k] = ov[k]

    return ThumbnailConfig(
        top_margin=g["top_margin"], bottom_margin=g["bottom_margin"],
        side_padding=g["side_padding"],
        font_size=g["font_size"], font_weight=FONT_WEIGHT,
        text_color=(0, 0, 0), text_padding=TEXT_PADDING,
        remove_bg_mode="white" if st.session_state.get("remove_bg", False) else "none",
        white_tolerance=WHITE_TOL, show_background=True,
        center_mode=g["center_mode"], product_scale=g["product_scale"],
        pill_left=PILL_LEFT, pill_right=PILL_RIGHT, pill_height=PILL_HEIGHT,
        pill1_top=PILL1_TOP, pill2_gap=PILL2_GAP,
        shadow_offset_x=SHADOW_X, shadow_offset_y=SHADOW_Y,
        shadow_blur=SHADOW_BLUR, shadow_opacity=SHADOW_OP,
        font_family=st.session_state.get("cfg_font_family", DEFAULT_FONT_FAMILY),
        text_y_nudge=TEXT_Y_NUDGE,  # <--- BẠN NHỚ THÊM DÒNG NÀY
    )


# ══════════════════════════════════════════════════════
# VALIDATION (kiểm tra trước khi xuất)
# ══════════════════════════════════════════════════════
def _validate_batch() -> List[dict]:
    """Kiểm tra toàn bộ SP, trả về list issues."""
    issues = []
    df = _effective_df()
    mapping = st.session_state.get("mapping", {})
    if df.empty: return issues

    # Trùng ID
    dupes = df[df["id"].duplicated(keep=False)]["id"].unique().tolist()
    if dupes:
        issues.append({"severity": "error", "type": "Trùng ID",
                       "message": f"{len(dupes)} ID bị trùng: {', '.join(dupes[:5])}"})

    for _, row in df.iterrows():
        pid = row["id"]
        t1, t2 = row["text1"], row["text2"]

        # Thiếu ảnh
        if pid not in mapping:
            issues.append({"severity": "error", "type": "Thiếu ảnh",
                           "pid": pid, "message": "Chưa có ảnh khớp"})
            continue

        # Text quá dài
        combined = (t1 + " " + t2).strip() if (t1 and t2) else (t1 or t2)
        if len(combined) > 45:
            issues.append({"severity": "warn", "type": "Text có thể shrink nhỏ",
                           "pid": pid, "message": f"Text dài {len(combined)} ký tự"})
        if not t1 and not t2:
            issues.append({"severity": "warn", "type": "Không có text",
                           "pid": pid, "message": "Cả text1 và text2 đều trống"})

        # Kiểm tra ảnh
        try:
            img = Image.open(io.BytesIO(mapping[pid]))
            img.verify()
            img = Image.open(io.BytesIO(mapping[pid]))  # reopen sau verify
            w, h = img.size
            if min(w, h) < MIN_SRC_DIM:
                issues.append({"severity": "warn", "type": "Ảnh nhỏ",
                               "pid": pid, "message": f"Ảnh {w}×{h} có thể bị vỡ khi zoom"})
        except UnidentifiedImageError:
            issues.append({"severity": "error", "type": "Ảnh hỏng",
                           "pid": pid, "message": "Không mở được file ảnh"})
        except Exception as e:
            issues.append({"severity": "error", "type": "Lỗi ảnh",
                           "pid": pid, "message": str(e)[:60]})

    return issues


# ══════════════════════════════════════════════════════
# CONFIG I/O (lưu/tải JSON)
# ══════════════════════════════════════════════════════
def _export_config() -> dict:
    return {
        "version": APP_VERSION,
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "preset_name": st.session_state.get("preset_name"),
        "global": {k[4:]: st.session_state[k] for k in st.session_state if k.startswith("cfg_")},
        "overrides": st.session_state.get("overrides", {}),
    }


def _import_config(data: dict):
    if "preset_name" in data and data["preset_name"] in PRESETS:
        st.session_state["preset_name"] = data["preset_name"]
    for k, v in (data.get("global") or {}).items():
        st.session_state[f"cfg_{k}"] = v
    if "overrides" in data:
        st.session_state["overrides"] = data["overrides"]


# ══════════════════════════════════════════════════════
# EMPTY STATE (reusable)
# ══════════════════════════════════════════════════════
def _empty_state(icon: str, message: str):
    with st.container(border=True):
        _, c, _ = st.columns([1, 2, 1])
        with c:
            st.markdown(f"<div style='text-align:center;padding:40px 0;'>"
                        f"<div style='font-size:48px;'>{icon}</div>"
                        f"<div style='color:#64748b;font-size:14px;margin-top:8px;'>{message}</div>"
                        f"</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 🖼️ Thumbnail Builder")
    st.caption(f"v{APP_VERSION} · Cấu hình toàn bộ")

    st.divider()

    # Preset
    st.markdown("**🎨 Preset nhanh**")
    sel = st.selectbox(
        "Preset", list(PRESETS.keys()),
        index=list(PRESETS.keys()).index(st.session_state["preset_name"]),
        label_visibility="collapsed",
    )
    if sel != st.session_state["preset_name"]:
        _apply_preset(sel)
        st.rerun()

    st.divider()
    st.markdown("**📐 Layout**")
    c1, c2 = st.columns(2)
    with c1: st.number_input("Mép trên", 0, 300, key="cfg_top_margin", step=5)
    with c2: st.number_input("Mép dưới", 0, 250, key="cfg_bottom_margin", step=5)
    c1, c2 = st.columns(2)
    with c1: st.number_input("Padding bên", 0, 100, key="cfg_side_padding", step=5)
    with c2: st.number_input("Zoom SP", 0.5, 1.5, key="cfg_product_scale",
                              step=0.05, format="%.2f")
    st.radio("Căn giữa", ["centroid", "bbox"], key="cfg_center_mode",
             horizontal=True, format_func=lambda x: "Trọng tâm" if x == "centroid" else "Khung")

    st.divider()
    st.markdown("**✒️ Font**")

    # Font family picker
    try:
        from image_processor import list_available_fonts
        available_fonts = list_available_fonts()
    except Exception:
        available_fonts = {}
    if available_fonts:
        font_list = list(available_fonts.keys())
        default_idx = 0
        for i, name in enumerate(font_list):
            if name == "Montserrat-Bold":  # <--- SỬA DÒNG NÀY ĐỂ ÉP CHỌN ĐÚNG BOLD
                default_idx = i; break
        st.selectbox(
            "Loại chữ", font_list, index=default_idx,
            key="cfg_font_family",
            help="Mặc định sử dụng Montserrat-Bold", # Sửa lại ghi chú cho đúng
        )
    else:
        st.session_state["cfg_font_family"] = None

    st.number_input("Kích thước", 9.0, 40.0, key="cfg_font_size", step=0.5, format="%.1f",
                    help="Mặc định 27 — khớp mẫu thumbnail chuẩn")

    st.divider()
    st.markdown("**📤 Xuất file**")
    st.toggle("Tách nền trắng", key="remove_bg",
              help="Bật nếu ảnh SP có nền trắng")
    out_fmt = st.selectbox("Định dạng", ["PNG", "JPG", "WEBP"])
    jpg_q = st.slider("Chất lượng", 70, 100, 92) if out_fmt in ("JPG", "WEBP") else 92

    st.divider()
    with st.expander("💾 Lưu / Tải cấu hình", expanded=False):
        st.caption("Sao lưu toàn bộ cấu hình (preset + override từng SP) ra file JSON.")
        cfg_json = json.dumps(_export_config(), indent=2, ensure_ascii=False)
        st.download_button("📥 Tải cấu hình (.json)", cfg_json,
                          f"config_{time.strftime('%Y%m%d_%H%M')}.json",
                          "application/json", use_container_width=True)
        up = st.file_uploader("📤 Nhập cấu hình", type=["json"],
                               label_visibility="collapsed", key="cfg_upload")
        if up and st.button("Áp dụng", use_container_width=True):
            try:
                _import_config(json.loads(up.getvalue().decode("utf-8")))
                st.success("Đã nhập!")
                st.rerun()
            except Exception as e:
                st.error(f"File không hợp lệ: {e}")

    st.divider()
    logout_btn()


# ══════════════════════════════════════════════════════
# HERO
# ══════════════════════════════════════════════════════
c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
with c1:
    st.markdown('<h1 class="hero-title">🖼️ Thumbnail Builder Pro</h1>', unsafe_allow_html=True)
    st.caption("Tạo thumbnail 600×600 hàng loạt · Smart-fit · Auto-shrink text · Montserrat")
df = st.session_state.get("df")
mapping = st.session_state.get("mapping", {})
ov_count = sum(1 for pid in (mapping or {})
               if any(k for k in st.session_state.get("overrides", {}).get(pid, {})
                      if k not in ("t1", "t2")))
with c2: st.metric("📋 Excel", len(df) if df is not None else 0)
with c3: st.metric("✅ Khớp ảnh", len(mapping))
with c4: st.metric("🎯 Tuỳ chỉnh", ov_count)


# ══════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════
tab_up, tab_single, tab_preview, tab_edit, tab_export = st.tabs([
    "📥 Upload",
    "🔬 Test nhanh",
    "👁️ Preview tất cả",
    "✏️ Chỉnh từng tấm",
    "📦 Xuất ZIP",
])


# ─── TAB 1: UPLOAD ───────────────────────────────────
with tab_up:
    st.markdown("### 📄 Bước 1 — File Excel / CSV")
    c1, c2 = st.columns([4, 1])
    with c1:
        excel_file = st.file_uploader(
            "Excel/CSV", type=["xlsx", "xls", "csv"],
            label_visibility="collapsed",
            help="Cột cần: id, text1, text2",
        )
    with c2:
        sample = pd.DataFrame({
            "id": ["SP001", "SP002", "SP003"],
            "text1": ["BLUETOOTH 5.4", "CHỐNG NƯỚC IPX7", "PIN 30H"],
            "text2": ["CỔNG SẠC TYPE-C", "", "SẠC NHANH"],
        })
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            sample.to_excel(w, index=False)
        st.download_button("📥 File mẫu", buf.getvalue(), "mau.xlsx",
                          use_container_width=True)

    if excel_file:
        try:
            df_new = _read_excel(excel_file)
            st.session_state["df"] = df_new
            st.success(f"✅ Đọc **{len(df_new)}** sản phẩm")
        except Exception as e:
            st.error(f"Lỗi đọc file: {e}")

    # Bulk edit text
    df = st.session_state.get("df")
    if df is not None:
        with st.expander("📝 Sửa text nhanh (tuỳ chọn)", expanded=False):
            st.caption("Chỉnh text1/text2 ngay tại đây, không cần sửa Excel")
            edited = st.data_editor(
                df, use_container_width=True, hide_index=True, num_rows="fixed",
                key="bulk_editor", disabled=["id"],
                height=min(350, 45 * len(df) + 38),
            )
            if not edited.equals(df):
                if st.button("💾 Lưu thay đổi text", use_container_width=True):
                    st.session_state["df"] = edited.reset_index(drop=True)
                    st.success("Đã lưu!")
                    st.rerun()

    st.divider()
    st.markdown("### 🖼️ Bước 2 — Ảnh sản phẩm")
    st.caption("Tên file chứa id SP (VD: `SP001.png`). Ảnh > 1600px sẽ tự nén để tiết kiệm RAM.")

    img_files = st.file_uploader(
        "Ảnh SP", type=["png","jpg","jpeg","webp"],
        accept_multiple_files=True, label_visibility="collapsed",
    )
    if img_files:
        # Kiểm tra file size
        oversize = [f.name for f in img_files if f.size > MAX_UPLOAD_MB * 1024 * 1024]
        if oversize:
            st.warning(f"⚠️ {len(oversize)} file > {MAX_UPLOAD_MB}MB sẽ bị bỏ qua: "
                       f"{', '.join(oversize[:3])}{'...' if len(oversize) > 3 else ''}")
        imgs_ok = [f for f in img_files if f.size <= MAX_UPLOAD_MB * 1024 * 1024]
        st.session_state["img_files"] = imgs_ok

    imgs = st.session_state.get("img_files")
    if df is not None and imgs:
        mapping, orig_names, matched, unmatched = _match(df, imgs)
        st.session_state["mapping"] = mapping
        st.session_state["orig_names"] = orig_names

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📋 Excel", len(df))
        c2.metric("✅ Khớp", len(matched))
        c3.metric("❌ Thiếu", len(unmatched))
        c4.metric("🖼️ Ảnh", len(imgs))

        if unmatched:
            with st.expander(f"⚠️ {len(unmatched)} SP chưa có ảnh"):
                st.write(unmatched)

    # ── VALIDATION PANEL ──
    if df is not None and mapping:
        st.divider()
        st.markdown("### 🔍 Kiểm tra chất lượng batch")
        c1, c2 = st.columns([1, 4])
        with c1:
            run_check = st.button("🔍 Kiểm tra", use_container_width=True, type="primary")
        with c2:
            st.caption("Quét tất cả SP trước khi xuất: text quá dài, ảnh nhỏ, thiếu text, trùng ID...")

        if run_check:
            with st.spinner("Đang quét..."):
                issues = _validate_batch()
            if not issues:
                st.success("🎉 Tất cả SP đều OK, sẵn sàng xuất!")
            else:
                errs = [i for i in issues if i["severity"] == "error"]
                warns = [i for i in issues if i["severity"] == "warn"]
                c1, c2, c3 = st.columns(3)
                c1.metric("❌ Lỗi nghiêm trọng", len(errs))
                c2.metric("⚠️ Cảnh báo", len(warns))
                c3.metric("✅ SP tốt", len(mapping) - len({i.get("pid") for i in issues if i.get("pid")}))

                idf = pd.DataFrame(issues)
                st.dataframe(idf, use_container_width=True, height=min(350, 40 * len(idf) + 40))


# ─── TAB 2: TEST NHANH ───────────────────────────────
with tab_single:
    st.markdown("### 🔬 Test 1 ảnh — preview tức thì")
    c_l, c_r = st.columns([1, 1], gap="large")
    with c_l:
        single_img = st.file_uploader("Ảnh SP", type=["png","jpg","jpeg","webp"], key="single_up")
        s_id = st.text_input("ID", "DEMO001")
        s_t1 = st.text_input("Text 1", "BLUETOOTH 5.4")
        s_t2 = st.text_input("Text 2", "CỔNG SẠC TYPE-C")

    with c_r:
        if single_img:
            try:
                prod = Image.open(io.BytesIO(single_img.getvalue()))
                bg = _bg()
                cfg = _build_config_for(None)
                thumb, info = build_thumbnail(prod, s_t1, s_t2, bg, cfg)
                st.image(thumb, use_container_width=True)
                sizes = info["font_sizes_used"]
                shrunk = " ⚡ shrunk" if info["any_shrunk"] else ""
                st.caption(f"600×600 · Font {sizes}{shrunk} · Ảnh gốc: {prod.size[0]}×{prod.size[1]}")
                fmt_low = out_fmt.lower()
                data = pil_to_bytes(thumb, fmt_low, jpg_q)
                st.download_button(f"⬇️ Tải {s_id}.{fmt_low}", data,
                                   f"{sanitize_filename(s_id)}.{fmt_low}",
                                   use_container_width=True)
            except Exception as e:
                st.error(f"Lỗi: {e}")
        else:
            _empty_state("🖼️", "Upload ảnh bên trái để xem preview")


# ─── TAB 3: PREVIEW ──────────────────────────────────
with tab_preview:
    df = _effective_df()
    mapping = st.session_state.get("mapping", {})

    if df.empty or not mapping:
        _empty_state("📋", "Hoàn tất tab Upload để xem preview")
    else:
        c1, c2, c3 = st.columns([3, 1, 1])
        with c1:
            search = st.text_input("🔍 Tìm", placeholder="ID hoặc text...", label_visibility="collapsed")
        with c2:
            cols_n = st.selectbox("Cột", [2, 3, 4, 6], index=2, label_visibility="collapsed")
        with c3:
            max_n = st.selectbox("Số", [12, 24, 48, 100], index=1, label_visibility="collapsed")

        dfv = df[df["id"].isin(mapping.keys())].copy()
        if search:
            s = search.lower()
            dfv = dfv[
                dfv["id"].str.lower().str.contains(s, na=False) |
                dfv["text1"].str.lower().str.contains(s, na=False) |
                dfv["text2"].str.lower().str.contains(s, na=False)
            ]

        if len(dfv) == 0:
            st.warning("Không tìm thấy kết quả.")
        else:
            ov_all = st.session_state.get("overrides", {})
            bg = _bg()
            rows = dfv.head(max_n).to_dict("records")
            prog = st.progress(0.0, text=f"Đang render {len(rows)} thumbnail...")
            cols = st.columns(cols_n)
            for i, row in enumerate(rows):
                prog.progress((i + 1) / len(rows))
                pid = row["id"]
                try:
                    prod = Image.open(io.BytesIO(mapping[pid]))
                    cfg = _build_config_for(pid)
                    thumb, info = build_thumbnail(prod, row["text1"], row["text2"], bg, cfg)
                    with cols[i % cols_n]:
                        with st.container(border=True):
                            st.image(thumb, use_container_width=True)
                            has_cfg = any(k for k in ov_all.get(pid, {}) if k not in ("t1","t2"))
                            badge = " 🎯" if has_cfg else ""
                            shrunk = " ⚡" if info["any_shrunk"] else ""
                            st.markdown(f"**{pid}**{badge}{shrunk}")
                            meta = row["text1"]
                            if row["text2"]: meta += f" · {row['text2']}"
                            st.caption(meta[:60] + ("…" if len(meta) > 60 else ""))
                except Exception as e:
                    with cols[i % cols_n]:
                        st.error(f"{pid}: {str(e)[:50]}")
            prog.empty()
            if len(dfv) > max_n:
                st.info(f"Hiện {max_n}/{len(dfv)} SP. Tăng 'Số' để xem thêm.")


# ─── TAB 4: CHỈNH TỪNG TẤM ───────────────────────────
with tab_edit:
    df = _effective_df()
    mapping = st.session_state.get("mapping", {})

    if df.empty or not mapping:
        _empty_state("✏️", "Hoàn tất tab Upload trước")
    else:
        st.markdown("### ✏️ Chỉnh riêng từng SP")
        st.caption("Mỗi SP có thể có cấu hình riêng, ghi đè config chung.")

        valid_ids = [pid for pid in df["id"].tolist() if pid in mapping]

        c1, c2, c3 = st.columns([3, 1, 1])
        with c1:
            ov_all = st.session_state.get("overrides", {})
            pid = st.selectbox(
                "Chọn SP", valid_ids,
                format_func=lambda x: f"🎯 {x}" if any(
                    k for k in ov_all.get(x, {}) if k not in ("t1", "t2")) else x,
            )
        idx = valid_ids.index(pid) if pid in valid_ids else 0
        with c2:
            if st.button("◀ Trước", use_container_width=True, disabled=idx == 0):
                st.session_state["_next_pid"] = valid_ids[idx - 1]; st.rerun()
        with c3:
            if st.button("Sau ▶", use_container_width=True, disabled=idx >= len(valid_ids) - 1):
                st.session_state["_next_pid"] = valid_ids[idx + 1]; st.rerun()

        if "_next_pid" in st.session_state:
            pid = st.session_state.pop("_next_pid")

        row = df[df["id"] == pid].iloc[0]
        ov = st.session_state.get("overrides", {}).get(pid, {})

        c_left, c_right = st.columns([1.1, 1], gap="large")
        with c_left:
            try:
                prod = Image.open(io.BytesIO(mapping[pid]))
                cfg = _build_config_for(pid)
                thumb, info = build_thumbnail(prod, row["text1"], row["text2"], _bg(), cfg)
                st.image(thumb, use_container_width=True)
                sizes = info["font_sizes_used"]
                shrunk = " ⚡ đã shrink" if info["any_shrunk"] else ""
                st.caption(f"600×600 · Font {sizes}{shrunk} · Gốc: {prod.size[0]}×{prod.size[1]}")
            except Exception as e:
                st.error(str(e))

        with c_right:
            with st.container(border=True):
                st.markdown(f"### ⚙️ Cấu hình: `{pid}`")

                use_ov = st.toggle(
                    "Bật cấu hình riêng",
                    value=bool(ov) and any(k for k in ov if k not in ("t1","t2")),
                    key=f"use_ov_{pid}",
                )

                if use_ov:
                    st.caption("Các giá trị ghi đè config chung ở sidebar.")
                    cur_top = ov.get("top_margin", st.session_state.get("cfg_top_margin", 155))
                    cur_bot = ov.get("bottom_margin", st.session_state.get("cfg_bottom_margin", 55))
                    cur_side = ov.get("side_padding", st.session_state.get("cfg_side_padding", 40))
                    cur_scale = ov.get("product_scale", st.session_state.get("cfg_product_scale", 1.0))
                    cur_center = ov.get("center_mode", st.session_state.get("cfg_center_mode", "centroid"))
                    cur_font = ov.get("font_size", st.session_state.get("cfg_font_size", 20.4))

                    c1, c2 = st.columns(2)
                    with c1:
                        new_top = st.number_input("Mép trên", 0, 300, int(cur_top), 5, key=f"ov_top_{pid}")
                        new_side = st.number_input("Padding bên", 0, 100, int(cur_side), 5, key=f"ov_side_{pid}")
                        new_scale = st.number_input("Zoom SP", 0.5, 1.5, float(cur_scale), 0.05,
                                                    format="%.2f", key=f"ov_scale_{pid}")
                    with c2:
                        new_bot = st.number_input("Mép dưới", 0, 250, int(cur_bot), 5, key=f"ov_bot_{pid}")
                        new_font = st.number_input("Font size", 9.0, 40.0, float(cur_font), 0.5,
                                                   format="%.1f", key=f"ov_font_{pid}")
                        new_center = st.radio("Căn", ["centroid","bbox"],
                                              index=0 if cur_center=="centroid" else 1,
                                              horizontal=True, key=f"ov_center_{pid}",
                                              format_func=lambda x: "Trọng tâm" if x == "centroid" else "Khung")

                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("💾 Lưu riêng", type="primary", use_container_width=True):
                            st.session_state.setdefault("overrides", {}).setdefault(pid, {}).update({
                                "top_margin": new_top, "bottom_margin": new_bot,
                                "side_padding": new_side, "product_scale": new_scale,
                                "center_mode": new_center, "font_size": new_font,
                            })
                            st.success("Đã lưu!"); st.rerun()
                    with c2:
                        # Nút sao chép cấu hình hiện tại sang SP khác
                        if st.button("📋 Copy → SP khác", use_container_width=True):
                            st.session_state["_copy_from"] = pid
                else:
                    if ov and any(k for k in ov if k not in ("t1","t2")):
                        if st.button("🗑️ Xoá cấu hình riêng", use_container_width=True):
                            new_ov = {k: v for k, v in ov.items() if k in ("t1","t2")}
                            if new_ov: st.session_state["overrides"][pid] = new_ov
                            else: st.session_state["overrides"].pop(pid, None)
                            st.rerun()
                    else:
                        st.info("SP này dùng config chung. Bật toggle để tuỳ chỉnh riêng.")

                # Copy-to dialog
                if st.session_state.get("_copy_from") == pid:
                    st.divider()
                    st.markdown("**📋 Sao chép sang các SP khác**")
                    targets = st.multiselect(
                        "Chọn SP đích (có thể chọn nhiều)",
                        [x for x in valid_ids if x != pid],
                        placeholder="Chọn SP để áp cấu hình này...",
                    )
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ Áp dụng", type="primary", use_container_width=True,
                                    disabled=not targets):
                            src_cfg = {k: v for k, v in ov.items() if k not in ("t1","t2")}
                            for t in targets:
                                st.session_state.setdefault("overrides", {}).setdefault(t, {}).update(src_cfg)
                            st.session_state.pop("_copy_from", None)
                            st.success(f"Đã áp cho {len(targets)} SP")
                            st.rerun()
                    with c2:
                        if st.button("❌ Huỷ", use_container_width=True):
                            st.session_state.pop("_copy_from", None); st.rerun()

                st.divider()
                st.markdown("**📝 Sửa text**")
                new_t1 = st.text_input("Text 1", value=row["text1"], key=f"t1_{pid}")
                new_t2 = st.text_input("Text 2", value=row["text2"], key=f"t2_{pid}")
                if new_t1 != row["text1"] or new_t2 != row["text2"]:
                    if st.button("💾 Lưu text", use_container_width=True, key=f"save_txt_{pid}"):
                        o = st.session_state.setdefault("overrides", {}).setdefault(pid, {})
                        o["t1"] = new_t1; o["t2"] = new_t2
                        base_df = st.session_state["df"]
                        base_df.loc[base_df["id"] == pid, "text1"] = new_t1
                        base_df.loc[base_df["id"] == pid, "text2"] = new_t2
                        st.success("Đã lưu!"); st.rerun()


# ─── TAB 5: XUẤT ZIP ─────────────────────────────────
with tab_export:
    df = _effective_df()
    mapping = st.session_state.get("mapping", {})

    if df.empty or not mapping:
        _empty_state("📦", "Hoàn tất tab Upload trước")
    else:
        n_total = len(mapping)
        n_ov = sum(1 for pid in mapping if any(
            k for k in st.session_state.get("overrides", {}).get(pid, {}) if k not in ("t1","t2")))

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🖼️ Thumbnail", n_total)
        c2.metric("📐 Format", out_fmt)
        c3.metric("📏 Size", "600²")
        c4.metric("🎯 Tuỳ chỉnh", n_ov)

        st.markdown("")
        with st.container(border=True):
            st.markdown("**⚙️ Tuỳ chọn xuất**")

            c1, c2 = st.columns(2)
            with c1:
                include_csv = st.checkbox("📄 Kèm CMS (csv + xlsx)", True)
                include_src = st.checkbox("🗂️ Kèm ảnh gốc (`source/`)", False,
                                         help="Nén ảnh gốc đã upload vào zip")
            with c2:
                multi_size = st.multiselect(
                    "🎯 Xuất thêm size khác (tuỳ chọn)",
                    [s for s in SUPPORTED_SIZES if s != 600],
                    default=[],
                    help="VD: chọn 300 + 800 → mỗi SP sẽ có 3 file size 600/300/800",
                )

            zip_name = st.text_input("Tên file ZIP",
                                     f"thumbnails_{time.strftime('%Y%m%d_%H%M')}.zip")

        st.markdown("")
        if st.button("🚀 Tạo & Tải ZIP", type="primary", use_container_width=True):
            all_sizes = [600] + sorted(multi_size)
            bg = _bg()
            fmt_low = out_fmt.lower()
            total_ops = len(mapping) * len(all_sizes)
            prog = st.progress(0.0, text="Đang render...")
            zbuf = io.BytesIO()
            cms = []
            errors = []
            t0 = time.time()
            dfex = df[df["id"].isin(mapping.keys())].reset_index(drop=True)
            done_ops = 0

            with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for i, row in dfex.iterrows():
                    pid = row["id"]
                    try:
                        prod = Image.open(io.BytesIO(mapping[pid]))
                        cfg = _build_config_for(pid)

                        # Render size 600 trước, các size khác resize từ đó (nhanh hơn)
                        thumb_600, info = build_thumbnail(prod, row["text1"], row["text2"], bg, cfg)
                        sid = sanitize_filename(pid)

                        for sz in all_sizes:
                            done_ops += 1
                            prog.progress(done_ops / total_ops,
                                         text=f"[{done_ops}/{total_ops}] {pid} @ {sz}px")
                            if sz == 600:
                                img_out = thumb_600
                            else:
                                img_out = thumb_600.resize((sz, sz), Image.LANCZOS)

                            subfolder = "thumbnails" if sz == 600 else f"thumbnails_{sz}"
                            fname = f"{sid}.{fmt_low}"
                            zf.writestr(f"{subfolder}/{fname}",
                                       pil_to_bytes(img_out, fmt_low, jpg_q))

                        if include_src:
                            orig_names = st.session_state.get("orig_names", {})
                            ext = Path(orig_names.get(pid, f"{pid}.png")).suffix or ".png"
                            zf.writestr(f"source/{sid}{ext}", mapping[pid])

                        has_ov = any(k for k in st.session_state.get("overrides", {}).get(pid, {})
                                    if k not in ("t1","t2"))
                        cms.append({
                            "id": pid, "text1": row["text1"], "text2": row["text2"],
                            "filename": f"{sid}.{fmt_low}",
                            "sizes": ";".join(str(s) for s in all_sizes),
                            "fonts": ";".join(str(s) for s in info["font_sizes_used"]),
                            "shrunk": "yes" if info["any_shrunk"] else "no",
                            "custom_config": "yes" if has_ov else "no",
                        })
                    except Exception as e:
                        done_ops += len(all_sizes)
                        prog.progress(done_ops / total_ops, text=f"Lỗi: {pid}")
                        errors.append(f"{pid}: {str(e)[:100]}")
                        cms.append({"id": pid, "text1": row.get("text1",""),
                                    "text2": row.get("text2",""), "filename": "ERROR",
                                    "sizes": "", "fonts": "", "shrunk": str(e)[:50],
                                    "custom_config": "no"})

                # CMS files
                if include_csv and cms:
                    cdf = pd.DataFrame(cms)
                    zf.writestr("cms.csv",
                                cdf.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"))
                    xb = io.BytesIO()
                    with pd.ExcelWriter(xb, engine="openpyxl") as w:
                        cdf.to_excel(w, index=False, sheet_name="CMS")
                    zf.writestr("cms.xlsx", xb.getvalue())

                # Config backup
                zf.writestr("config_snapshot.json",
                           json.dumps(_export_config(), indent=2, ensure_ascii=False))

                # README
                zf.writestr("README.txt",
                           f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                           f"App version: {APP_VERSION}\n"
                           f"Items: {len(dfex)}\n"
                           f"Sizes: {all_sizes}\n"
                           f"Format: {fmt_low.upper()}\n"
                           f"Custom config: {n_ov}\n"
                           f"Errors: {len(errors)}\n")

            prog.empty()
            elapsed = time.time() - t0

            if errors:
                st.warning(f"⚠️ {len(errors)} SP bị lỗi (vẫn được ghi vào ZIP)")
                with st.expander("Xem lỗi"):
                    for e in errors[:20]: st.text(e)
            else:
                st.success(f"✅ Hoàn tất {len(dfex)} SP × {len(all_sizes)} size trong {elapsed:.1f}s")

            st.download_button("⬇️ TẢI FILE ZIP", zbuf.getvalue(), zip_name,
                             "application/zip", use_container_width=True)
