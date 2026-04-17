"""
app.py — Thumbnail Builder Pro
"""
from __future__ import annotations

import io
import os
import time
import zipfile
import copy
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
from PIL import Image

from auth import logout_button, require_login
from image_processor import (
    CANVAS_SIZE,
    DEFAULT_BOTTOM_MARGIN,
    DEFAULT_FONT_SIZE,
    DEFAULT_TOP_MARGIN,
    ThumbnailConfig,
    build_thumbnail,
    pil_to_bytes,
    sanitize_filename,
)

# ============ CẤU HÌNH TRANG ============
st.set_page_config(
    page_title="Thumbnail Builder Pro",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Đã fix lỗi UI lẹm góc bằng cách điều chỉnh block-container padding & width
st.markdown(
    """
    <style>
      #MainMenu {visibility: hidden;}
      footer {visibility: hidden;}
      header [data-testid="stToolbar"] {visibility: hidden;}
      .block-container {padding-top: 1.5rem; padding-bottom: 2rem; padding-left: 2rem; padding-right: 2rem; max-width: 98%;}
      .stat-card {
        background: linear-gradient(135deg, #f8fafc 0%, #eef2f7 100%);
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 14px 18px;
      }
      .stat-card h3 {margin: 0; color: #0f172a; font-size: 28px;}
      .stat-card p {margin: 0; color: #64748b; font-size: 13px;}
      .thumb-tile {
        background: #fff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 10px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        margin-bottom: 8px;
      }
      .thumb-tile img {border-radius: 8px; width: 100%; display:block;}
      .thumb-id {font-weight: 700; font-size: 14px; color: #111827;}
      .thumb-meta {font-size: 12px; color: #6b7280; margin-top: 4px;}
      .stButton>button {border-radius: 10px; font-weight: 600;}
      .stDownloadButton>button {
        border-radius: 10px; font-weight: 700;
        background: linear-gradient(135deg, #4f46e5, #7c3aed);
        color: white; border: none;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

if not require_login():
    st.stop()

# Khởi tạo cache ghi đè (overrides) cho từng ảnh
if "overrides" not in st.session_state:
    st.session_state["overrides"] = {}

# ============ HELPERS ============
ASSETS_DIR = Path(__file__).parent / "assets"

@st.cache_resource(show_spinner=False)
def load_background() -> Image.Image:
    return Image.open(ASSETS_DIR / "background.png").convert("RGBA")

def read_excel_safe(file) -> pd.DataFrame:
    name = getattr(file, "name", "").lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(file, dtype=str, keep_default_na=False)

    df.columns = [str(c).strip().lower().replace(" ", "") for c in df.columns]
    col_map: Dict[str, str] = {}
    for c in df.columns:
        if c in ("id", "sku", "masp", "ma", "productid", "code"): col_map[c] = "id"
        elif c in ("text1", "tt1", "dong1", "line1", "title1"): col_map[c] = "text1"
        elif c in ("text2", "tt2", "dong2", "line2", "title2"): col_map[c] = "text2"
    df = df.rename(columns=col_map)

    for col in ("id", "text1", "text2"):
        if col not in df.columns: df[col] = ""

    df = df[["id", "text1", "text2"]].copy()
    df["id"] = df["id"].astype(str).str.strip()
    df["text1"] = df["text1"].astype(str).str.strip()
    df["text2"] = df["text2"].astype(str).str.strip()
    df = df[df["id"] != ""].reset_index(drop=True)
    return df

def match_images_by_id(df: pd.DataFrame, uploaded_images: List) -> Tuple[Dict[str, bytes], Dict[str, str], List[str], List[str]]:
    img_by_stem: Dict[str, Tuple[bytes, str]] = {}
    for f in uploaded_images:
        stem = Path(f.name).stem.strip().lower()
        img_by_stem[stem] = (f.getvalue(), f.name)

    mapping, orig_names, matched, unmatched = {}, {}, [], []
    for pid in df["id"].tolist():
        key = str(pid).strip().lower()
        hit = None
        if key in img_by_stem: hit = img_by_stem[key]
        else:
            for stem, data_name in img_by_stem.items():
                if key in stem or stem in key:
                    hit = data_name
                    break
        if hit is not None:
            mapping[pid] = hit[0]
            orig_names[pid] = hit[1]
            matched.append(pid)
        else:
            unmatched.append(pid)
    return mapping, orig_names, matched, unmatched

def build_config_from_sidebar() -> Tuple[ThumbnailConfig, dict]:
    with st.sidebar:
        st.markdown("### ⚙️ Cấu hình chung")

        with st.expander("📐 Layout sản phẩm", expanded=True):
            top_m = st.slider("Mép trên → SP (px)", 0, 300, 155)
            bot_m = st.slider("Mép dưới → SP (px)", 0, 250, 55)
            side_p = st.slider("Padding 2 bên (px)", 0, 100, 40)
            center_mode_label = st.radio("Chế độ căn giữa sản phẩm", ["Theo trọng tâm (centroid) — khuyên dùng", "Theo khung bbox"], index=0)
            center_mode = "centroid" if center_mode_label.startswith("Theo trọng tâm") else "bbox"
            prod_scale = st.slider("Zoom sản phẩm", 0.5, 1.3, 1.0, step=0.05)

        with st.expander("✒️ Text & Font", expanded=True):
            font_size = st.slider("Font size (Montserrat)", 9.0, 30.0, 20.4, step=0.1)
            weight_label = st.select_slider("Độ đậm", options=["Regular (400)", "Medium (500)", "SemiBold (600)", "Bold (700)", "ExtraBold (800)", "Black (900)"], value="ExtraBold (800)")
            weight_map = {"Regular (400)": 400, "Medium (500)": 500, "SemiBold (600)": 600, "Bold (700)": 700, "ExtraBold (800)": 800, "Black (900)": 900}
            font_weight = weight_map[weight_label]
            color_hex = st.color_picker("Màu chữ", "#000000")
            text_color = tuple(int(color_hex[i:i+2], 16) for i in (1, 3, 5))

        with st.expander("🎨 Pill (khung text)", expanded=True):
            pill_left = st.slider("Vị trí lề trái (px)", 0, 100, 20)
            pill_height = st.slider("Chiều cao ô (px)", 30, 80, 49)
            pill1_top = st.slider("Cách mép trên (px)", 0, 100, 8)
            pill2_gap = st.slider("Khoảng cách 2 ô (px)", 0, 40, 11)
            text_pad = st.slider("Độ rộng lề chữ (Padding)", 10, 60, 25)
            
            st.markdown("**Bóng đổ (Đã lưu thông số tối ưu)**")
            sh_x = st.slider("Shadow X", -10, 10, 3)
            sh_y = st.slider("Shadow Y", -10, 15, 5)
            sh_blur = st.slider("Shadow Blur", 0, 30, 5)
            sh_op = st.slider("Shadow Opacity", 0, 255, 112)
            pill_right = 300

        with st.expander("🪄 Tách nền trắng (tuỳ chọn)", expanded=False):
            bg_mode_label = st.radio("Chế độ tách nền", ["Không tách", "Tách nền trắng (khuyến nghị)"], index=0)
            bg_mode = "white" if bg_mode_label == "Tách nền trắng (khuyến nghị)" else "none"
            white_tol = st.slider("Độ nhạy nền trắng", 5, 40, 18, disabled=(bg_mode != "white"))
            show_bg = st.checkbox("Dùng background mẫu", value=True)

        st.divider()
        out_format = st.radio("Định dạng xuất", ["PNG", "JPG"], horizontal=True)
        jpg_quality = st.slider("Chất lượng JPG", 70, 100, 92, disabled=(out_format != "JPG"))
        st.divider()
        logout_button()

    cfg = ThumbnailConfig(
        top_margin=top_m, bottom_margin=bot_m, side_padding=side_p,
        font_size=font_size, font_weight=font_weight, text_color=text_color, text_padding=text_pad,
        remove_bg_mode=bg_mode, white_tolerance=white_tol, show_background=show_bg,
        center_mode=center_mode, product_scale=prod_scale,
        pill_left=pill_left, pill_right=pill_right, pill_height=pill_height, pill1_top=pill1_top, pill2_gap=pill2_gap,
        shadow_offset_x=sh_x, shadow_offset_y=sh_y, shadow_blur=sh_blur, shadow_opacity=sh_op,
    )
    meta = {"format": out_format, "jpg_quality": jpg_quality}
    return cfg, meta

# ============ HEADER ============
st.markdown(
    """
    <div style='display:flex; align-items:center; justify-content:space-between;
                padding: 8px 16px; border-radius: 14px;
                background: linear-gradient(135deg,#4f46e5 0%,#7c3aed 100%);
                color:white; margin-bottom: 18px;'>
      <div>
        <div style='font-size:26px; font-weight:800; letter-spacing:-0.5px;'>🖼️ Thumbnail Builder Pro</div>
        <div style='opacity:0.9; font-size:14px;'>Tạo thumbnail sản phẩm 600×600 hàng loạt · Cập nhật Fix Răng Cưa</div>
      </div>
      <div style='text-align:right; font-size:12px; opacity:0.85;'>
        <div>Rule mặc định: top 155px · bot 55px · side 40px</div>
        <div>Font size: 20.4 · Text padding: 25px · Auto co giãn</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

cfg, out_meta = build_config_from_sidebar()

# ============ TABS ============
tab_upload, tab_single, tab_preview, tab_export = st.tabs(
    ["📥 1. Upload", "🎨 2. Chỉnh sửa từng tấm", "👁️ 3. Preview hàng loạt", "📦 4. Xuất ZIP"]
)

with tab_upload:
    col1, col2 = st.columns([3, 2])
    with col1:
        excel_file = st.file_uploader("File Excel (.xlsx, .xls) hoặc CSV", type=["xlsx", "xls", "csv"])
    with col2:
        st.markdown("**📌 Cột cần có:** `id` (mã SP), `text1` (dòng 1), `text2` (dòng 2)")

    if excel_file:
        try:
            df = read_excel_safe(excel_file)
            st.session_state["df"] = df
            st.success(f"✅ Đọc được **{len(df)}** sản phẩm.")
        except Exception as e:
            st.error(f"❌ Lỗi: {e}")

    st.markdown("---")
    img_files = st.file_uploader("Ảnh (PNG, JPG, WEBP) - chọn nhiều", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True)
    if img_files:
        st.session_state["img_files"] = img_files
        st.success(f"✅ Đã nhận **{len(img_files)}** ảnh.")

    df = st.session_state.get("df")
    imgs = st.session_state.get("img_files")
    if df is not None and imgs:
        mapping, orig_names, matched, unmatched = match_images_by_id(df, imgs)
        st.session_state["mapping"] = mapping
        st.session_state["orig_names"] = orig_names
        
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"<div class='stat-card'><h3>{len(df)}</h3><p>Dòng Excel</p></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='stat-card'><h3>{len(matched)}</h3><p>Khớp ảnh</p></div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='stat-card'><h3>{len(unmatched)}</h3><p>Thiếu ảnh</p></div>", unsafe_allow_html=True)

# ============ CHỈNH SỬA TỪNG TẤM ============
with tab_single:
    st.markdown("#### 🎨 Chỉnh sửa & Ghi đè cài đặt cho từng ảnh")
    df = st.session_state.get("df")
    mapping = st.session_state.get("mapping", {})

    if df is not None and mapping:
        st.caption("Bạn có thể chọn 1 sản phẩm cụ thể để chỉnh Text, Zoom, Margin (ưu tiên cao hơn Sidebar chung).")
        sel_id = st.selectbox("Chọn Mã SP để tinh chỉnh:", list(mapping.keys()))
        
        ov = st.session_state["overrides"].get(sel_id, {})
        row_data = df[df['id'] == sel_id].iloc[0]
        
        # Mặc định lấy từ override nếu có, nếu không lấy từ df / global config
        def_t1 = ov.get('text1', row_data['text1'])
        def_t2 = ov.get('text2', row_data['text2'])
        def_zoom = ov.get('zoom', cfg.product_scale)
        def_top = ov.get('top_margin', cfg.top_margin)
        def_bot = ov.get('bottom_margin', cfg.bottom_margin)

        colA, colB = st.columns([1, 1])
        with colA:
            new_t1 = st.text_input("Ghi đè Text 1", def_t1, key=f"t1_{sel_id}")
            new_t2 = st.text_input("Ghi đè Text 2", def_t2, key=f"t2_{sel_id}")
            new_zoom = st.slider("Ghi đè Zoom sản phẩm", 0.5, 1.5, def_zoom, step=0.05, key=f"z_{sel_id}")
            new_top = st.slider("Ghi đè Margin TOP", 0, 300, def_top, key=f"top_{sel_id}")
            new_bot = st.slider("Ghi đè Margin BOT", 0, 300, def_bot, key=f"bot_{sel_id}")
            
            c_btn1, c_btn2 = st.columns(2)
            if c_btn1.button("💾 Lưu tinh chỉnh ảnh này", type="primary"):
                st.session_state["overrides"][sel_id] = {
                    'text1': new_t1, 'text2': new_t2, 'zoom': new_zoom,
                    'top_margin': new_top, 'bottom_margin': new_bot
                }
                st.success("Đã ghi nhớ cho ảnh này!")
            if c_btn2.button("🗑️ Xoá ghi đè"):
                if sel_id in st.session_state["overrides"]:
                    del st.session_state["overrides"][sel_id]
                    st.success("Đã đưa về mặc định chung!")
                    st.rerun()

        with colB:
            prod = Image.open(io.BytesIO(mapping[sel_id]))
            bg = load_background()
            
            # Tạo local_config kết hợp global config + override hiện tại
            local_cfg = copy.deepcopy(cfg)
            local_cfg.product_scale = new_zoom
            local_cfg.top_margin = new_top
            local_cfg.bottom_margin = new_bot
            
            thumb, info = build_thumbnail(prod, new_t1, new_t2, bg, local_cfg)
            st.image(thumb, caption=f"Live Preview: {sel_id}", use_container_width=True)
            
    else:
        st.info("👈 Vui lòng Upload Excel và Ảnh ở Bước 1 trước khi dùng tính năng này.")


# ============ PREVIEW HÀNG LOẠT ============
with tab_preview:
    df = st.session_state.get("df")
    mapping = st.session_state.get("mapping", {})

    if df is None or not mapping:
        st.info("👈 Hoàn tất bước 1 (upload Excel + ảnh) để xem preview hàng loạt.")
    else:
        st.markdown(f"#### 👁️ Preview {len(mapping)} thumbnail")
        c1, c2, c3 = st.columns([2, 1, 1])
        search = c1.text_input("🔍 Tìm theo ID hoặc text", "")
        cols_per_row = c2.selectbox("Cột / hàng", [2, 3, 4, 6], index=2)
        max_preview = c3.selectbox("Số thumbnail preview", [12, 24, 48, 100], index=1)

        df_view = df[df["id"].isin(mapping.keys())].copy()
        if search:
            s = search.lower()
            df_view = df_view[df_view["id"].str.lower().str.contains(s) | df_view["text1"].str.lower().str.contains(s) | df_view["text2"].str.lower().str.contains(s)]

        if len(df_view) == 0:
            st.warning("Không có kết quả khớp.")
        else:
            bg = load_background()
            view_rows = df_view.head(max_preview).to_dict("records")
            with st.spinner(f"Đang render..."):
                cols = st.columns(cols_per_row)
                for i, row in enumerate(view_rows):
                    pid = row["id"]
                    try:
                        # Kiểm tra xem có override riêng cho ảnh này không
                        ov = st.session_state["overrides"].get(pid, {})
                        t1 = ov.get('text1', row["text1"])
                        t2 = ov.get('text2', row["text2"])
                        
                        local_cfg = cfg
                        if ov:
                            local_cfg = copy.deepcopy(cfg)
                            local_cfg.product_scale = ov.get('zoom', cfg.product_scale)
                            local_cfg.top_margin = ov.get('top_margin', cfg.top_margin)
                            local_cfg.bottom_margin = ov.get('bottom_margin', cfg.bottom_margin)

                        prod = Image.open(io.BytesIO(mapping[pid]))
                        thumb, info = build_thumbnail(prod, t1, t2, bg, local_cfg)
                        
                        with cols[i % cols_per_row]:
                            st.markdown("<div class='thumb-tile'>", unsafe_allow_html=True)
                            st.image(thumb, use_container_width=True)
                            badge = " 🛠️(Đã ghi đè)" if ov else ""
                            st.markdown(f"<div class='thumb-id'>{pid}{badge}</div><div class='thumb-meta'>{t1}<br>{t2}</div></div>", unsafe_allow_html=True)
                    except Exception as e:
                        cols[i % cols_per_row].error(f"❌ {pid}: {e}")

# ============ EXPORT ZIP (CHỈ HÌNH ẢNH) ============
with tab_export:
    df = st.session_state.get("df")
    mapping = st.session_state.get("mapping", {})

    if df is None or not mapping:
        st.info("👈 Hoàn tất bước 1 để xuất ZIP.")
    else:
        st.markdown(f"#### 📦 Xuất {len(mapping)} thumbnail")
        st.caption("File ZIP chỉ chứa thư mục ảnh (không kèm Excel theo yêu cầu). Quá trình render sẽ áp dụng cả cấu hình chung và Cấu hình tuỳ chỉnh từng ảnh (nếu có).")

        colL, colR = st.columns([2, 1])
        with colL:
            zip_name = st.text_input("Tên file ZIP", f"thumbnails_final_{time.strftime('%Y%m%d_%H%M%S')}.zip")
        with colR:
            st.markdown(f"<div class='stat-card' style='text-align:center;'><h3>{len(mapping)}</h3><p>File ảnh {out_meta['format']}</p></div>", unsafe_allow_html=True)

        if st.button("🚀 Tạo file ZIP ngay", type="primary", use_container_width=True):
            bg = load_background()
            fmt = out_meta["format"].lower()
            progress = st.progress(0.0, text="Chuẩn bị...")
            zip_buf = io.BytesIO()

            t0 = time.time()
            df_export = df[df["id"].isin(mapping.keys())].reset_index(drop=True)
            total = len(df_export)

            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for i, row in df_export.iterrows():
                    pid = row["id"]
                    progress.progress((i + 1) / total, text=f"Đang render [{i+1}/{total}]  {pid}")
                    try:
                        # Tích hợp override khi xuất
                        ov = st.session_state["overrides"].get(pid, {})
                        t1 = ov.get('text1', row["text1"])
                        t2 = ov.get('text2', row["text2"])
                        
                        local_cfg = cfg
                        if ov:
                            local_cfg = copy.deepcopy(cfg)
                            local_cfg.product_scale = ov.get('zoom', cfg.product_scale)
                            local_cfg.top_margin = ov.get('top_margin', cfg.top_margin)
                            local_cfg.bottom_margin = ov.get('bottom_margin', cfg.bottom_margin)

                        prod = Image.open(io.BytesIO(mapping[pid]))
                        thumb, info = build_thumbnail(prod, t1, t2, bg, local_cfg)
                        
                        safe_id = sanitize_filename(pid)
                        fname = f"{safe_id}.{fmt}"
                        zf.writestr(f"thumbnails/{fname}", pil_to_bytes(thumb, fmt, out_meta["jpg_quality"]))
                    except Exception as e:
                        pass # Bỏ qua nếu lỗi hình

            progress.empty()
            elapsed = time.time() - t0
            st.success(f"✅ Hoàn tất {total} thumbnail trong {elapsed:.1f}s.")

            st.download_button("⬇️ TẢI FILE ZIP VỀ MÁY", zip_buf.getvalue(), zip_name, "application/zip", use_container_width=True)
