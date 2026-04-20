"""
app.py — Thumbnail Builder Pro
==============================
Streamlit web app tạo thumbnail sản phẩm 600x600 hàng loạt.

Quy trình sử dụng:
  1. Đăng nhập
  2. Upload file Excel (cột: id, text1, text2) + folder/nhiều ảnh sản phẩm
  3. App tự khớp ảnh theo id, preview thumbnail trong grid
  4. Chỉnh margin, font, weight, tách nền, ... bằng sidebar (live preview)
  5. Download ZIP chứa tất cả thumbnail + file CSV CMS

Để ẩn code khi deploy: push lên GitHub PRIVATE rồi connect Streamlit Cloud.
Người dùng cuối chỉ thấy UI, không thấy source.
"""

from __future__ import annotations

import io
import os
import time
import zipfile
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
    menu_items={
        "About": "Thumbnail Builder Pro — Tạo thumbnail 600×600 hàng loạt.",
    },
)

# Ẩn menu & footer mặc định của Streamlit cho gọn
st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header [data-testid="stToolbar"] {visibility: hidden;}
    .block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1400px;}
    /* Card styling */
    .stat-card {
        background: linear-gradient(135deg, #f8fafc 0%, #eef2f7 100%);
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 14px 18px;
    }
    .stat-card h3 {margin: 0; color: #0f172a; font-size: 28px;}
    .stat-card p {margin: 0; color: #64748b; font-size: 13px;}
    /* Preview tile */
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
    /* Action bar */
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

# ============ LOGIN GATE ============
if not require_login():
    st.stop()

# ============ HELPERS ============
ASSETS_DIR = Path(__file__).parent / "assets"


@st.cache_resource(show_spinner=False)
def load_background() -> Image.Image:
    return Image.open(ASSETS_DIR / "background.png").convert("RGBA")


def read_excel_safe(file) -> pd.DataFrame:
    """Đọc Excel/CSV với các tên cột linh hoạt (id, text1, text2)."""
    name = getattr(file, "name", "").lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(file, dtype=str, keep_default_na=False)

    # Chuẩn hoá tên cột: lowercase, bỏ dấu cách
    df.columns = [str(c).strip().lower().replace(" ", "") for c in df.columns]

    # Map linh hoạt
    col_map: Dict[str, str] = {}
    for c in df.columns:
        if c in ("id", "sku", "masp", "ma", "productid", "code"):
            col_map[c] = "id"
        elif c in ("text1", "tt1", "dong1", "line1", "title1"):
            col_map[c] = "text1"
        elif c in ("text2", "tt2", "dong2", "line2", "title2"):
            col_map[c] = "text2"
    df = df.rename(columns=col_map)

    for col in ("id", "text1", "text2"):
        if col not in df.columns:
            df[col] = ""
    df = df[["id", "text1", "text2"]].copy()
    df["id"] = df["id"].astype(str).str.strip()
    df["text1"] = df["text1"].astype(str).str.strip()
    df["text2"] = df["text2"].astype(str).str.strip()
    df = df[df["id"] != ""].reset_index(drop=True)
    return df


def match_images_by_id(
    df: pd.DataFrame,
    uploaded_images: List,
) -> Tuple[Dict[str, bytes], Dict[str, str], List[str], List[str]]:
    """
    Khớp ảnh với id trong excel.
    Logic: tên file chứa id (không phân biệt hoa thường, bỏ extension).
    """
    img_by_stem: Dict[str, Tuple[bytes, str]] = {}
    for f in uploaded_images:
        stem = Path(f.name).stem.strip().lower()
        img_by_stem[stem] = (f.getvalue(), f.name)

    mapping: Dict[str, bytes] = {}
    orig_names: Dict[str, str] = {}
    matched, unmatched = [], []

    for pid in df["id"].tolist():
        key = str(pid).strip().lower()
        hit = None
        if key in img_by_stem:
            hit = img_by_stem[key]
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
    """Render sidebar controls và trả về ThumbnailConfig + metadata."""
    with st.sidebar:
        st.markdown("### ⚙️ Cấu hình thumbnail")

        with st.expander("📐 Layout sản phẩm", expanded=True):
            st.caption("💡 Preset mặc định: sản phẩm cân giữa, không bị pill che, không sát viền.")

            top_m = st.slider(
                "Mép trên → SP (px)",
                0, 300, 155,
                help="Khoảng cách từ mép trên thumbnail đến đỉnh sản phẩm. "
                     "Mặc định 155: sản phẩm nằm dưới pill, không bị che.",
            )
            bot_m = st.slider(
                "Mép dưới → SP (px)",
                0, 250, 55,
                help="Khoảng cách từ mép dưới thumbnail đến đáy sản phẩm. Mặc định 55.",
            )
            side_p = st.slider(
                "Padding 2 bên (px)", 0, 100, 40,
                help="Cách đều 2 bên trái/phải. Mặc định 40 để sp không sát viền.",
            )
            center_mode_label = st.radio(
                "Chế độ căn giữa sản phẩm",
                ["Theo trọng tâm (centroid) — khuyên dùng", "Theo khung bbox"],
                index=0,
                help="Centroid cân cho sp bất đối xứng (chảo, ấm có cán...). "
                     "Bbox cân cho sp đối xứng (chai, hộp vuông...).",
            )
            center_mode = "centroid" if center_mode_label.startswith("Theo trọng tâm") else "bbox"

            prod_scale = st.slider(
                "Zoom sản phẩm", 0.5, 1.3, 1.0, step=0.05,
                help="Phóng to/thu nhỏ sản phẩm trong khung. 1.0 = tự fit vừa khung.",
            )

        with st.expander("✒️ Text & Font", expanded=True):
            font_size = st.slider(
                "Font size (Montserrat)",
                9.0, 30.0, float(DEFAULT_FONT_SIZE), step=0.1,
                help="Text dài sẽ tự shrink. Text ngắn giữ nguyên size này.",
            )
            text_pad = st.slider(
                "Text thụt vào pill (px)", 10, 50, 18,
                help="Khoảng cách từ mép pill đến chữ. Mặc định 18 (đo từ ảnh mẫu).",
            )
            weight_label = st.select_slider(
                "Độ đậm",
                options=["Regular (400)", "Medium (500)", "SemiBold (600)",
                         "Bold (700)", "ExtraBold (800)", "Black (900)"],
                value="ExtraBold (800)",
            )
            weight_map = {"Regular (400)": 400, "Medium (500)": 500, "SemiBold (600)": 600,
                          "Bold (700)": 700, "ExtraBold (800)": 800, "Black (900)": 900}
            font_weight = weight_map[weight_label]

            color_hex = st.color_picker("Màu chữ", "#000000")
            text_color = tuple(int(color_hex[i:i + 2], 16) for i in (1, 3, 5))

        with st.expander("🎨 Pill (khung text)", expanded=False):
            st.caption("⚡ Giá trị mặc định đã đo chính xác từ ảnh mẫu chuẩn.")
            pill_left = st.slider("Pill left (px)", 0, 100, 15,
                                  help="Mặc định 15 — khớp guide V-line.")
            pill_height = st.slider("Pill height (px)", 30, 80, 52,
                                    help="Mặc định 52 — FIX CỨNG chiều cao. Chiều rộng tự co theo text.")
            pill1_top = st.slider("Pill 1 top (px)", 0, 100, 5,
                                  help="Mặc định 5 — khớp guide H-line trên cùng.")
            pill2_gap = st.slider("Khoảng cách giữa 2 pill (px)", 0, 40, 13,
                                  help="Mặc định 13 — khớp guide.")

            st.markdown("**Shadow**")
            sh_x = st.slider("Shadow X offset", -10, 10, 3)
            sh_y = st.slider("Shadow Y offset", -10, 15, 5)
            sh_blur = st.slider("Shadow blur", 0, 20, 5)
            sh_op = st.slider("Shadow opacity", 0, 255, 112)

        with st.expander("🪄 Tách nền trắng (tuỳ chọn)", expanded=False):
            bg_mode_label = st.radio(
                "Chế độ tách nền",
                ["Không tách", "Tách nền trắng (khuyến nghị)"],
                index=0,
                help="Tách nền trắng dùng flood-fill — không cần AI, giữ chi tiết tốt. "
                     "Phù hợp với ảnh sản phẩm trên nền trắng sạch.",
            )
            bg_mode = {"Không tách": "none",
                       "Tách nền trắng (khuyến nghị)": "white"}[bg_mode_label]

            white_tol = st.slider(
                "Độ nhạy với nền trắng", 5, 40, 18, disabled=(bg_mode != "white"),
                help="Càng cao càng 'ăn' cả xám nhạt. Với nền trắng tinh, để 15-20.",
            )

            show_bg = st.checkbox(
                "Dùng background mẫu (ảnh Nền.png)", value=True,
                help="Bỏ tick để nền trắng tinh thay vì background có shadow.",
            )

        st.divider()

        st.markdown("### 📤 Xuất file")
        out_format = st.radio("Định dạng", ["PNG", "JPG"], horizontal=True)
        jpg_quality = st.slider("Chất lượng JPG", 70, 100, 92, disabled=(out_format != "JPG"))

        st.divider()
        logout_button()

    cfg = ThumbnailConfig(
        top_margin=top_m,
        bottom_margin=bot_m,
        side_padding=side_p,
        font_size=font_size,
        font_weight=font_weight,
        text_color=text_color,
        text_padding=text_pad,
        remove_bg_mode=bg_mode,
        white_tolerance=white_tol,
        show_background=show_bg,
        center_mode=center_mode,
        product_scale=prod_scale,
        pill_left=pill_left,
        pill_right=300,       # không dùng trực tiếp — width tự tính
        pill_height=pill_height,
        pill1_top=pill1_top,
        pill2_gap=pill2_gap,
        shadow_offset_x=sh_x,
        shadow_offset_y=sh_y,
        shadow_blur=sh_blur,
        shadow_opacity=sh_op,
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
            <div style='font-size:26px; font-weight:800; letter-spacing:-0.5px;'>
                🖼️ Thumbnail Builder Pro
            </div>
            <div style='opacity:0.9; font-size:14px;'>
                Tạo thumbnail sản phẩm 600×600 hàng loạt · Montserrat · Smart-fit · Cap-height centering
            </div>
        </div>
        <div style='text-align:right; font-size:12px; opacity:0.85;'>
            <div>Rule: top 155px · bot 55px · side 40px</div>
            <div>Pill: left 15 · height 52 · gap 13 · pad 18</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ============ SIDEBAR CONFIG ============
cfg, out_meta = build_config_from_sidebar()


# ============ UPLOAD ============
tab_upload, tab_single, tab_preview, tab_export = st.tabs(
    ["📥 1. Upload dữ liệu", "🧪 2. Test đơn lẻ", "👁️ 3. Preview hàng loạt", "📦 4. Xuất ZIP"]
)

with tab_upload:
    st.markdown("#### 📄 Bước 1 — File Excel/CSV (bắt buộc)")
    col1, col2 = st.columns([3, 2])
    with col1:
        excel_file = st.file_uploader(
            "File Excel (.xlsx, .xls) hoặc CSV",
            type=["xlsx", "xls", "csv"],
            help="Cột cần có: **id** (mã SP), **text1**, **text2**. "
                 "Cột khác sẽ bị bỏ qua. Hỗ trợ tên cột tiếng Việt: masp, tt1, tt2...",
        )
    with col2:
        st.markdown(
            """
            **📌 Quy ước cột**
            - `id` / `sku` / `masp` → mã SP
            - `text1` / `tt1` / `dong1` → dòng 1
            - `text2` / `tt2` / `dong2` → dòng 2
            """
        )
        # Nút tạo file mẫu
        sample = pd.DataFrame({
            "id": ["SP001", "SP002", "SP003"],
            "text1": ["BLUETOOTH 5.4", "CHỐNG NƯỚC IPX7", "PIN 30H"],
            "text2": ["CỔNG SẠC TYPE-C", "", "SẠC NHANH"],
        })
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            sample.to_excel(w, index=False, sheet_name="Products")
        st.download_button(
            "📥 Tải Excel mẫu",
            buf.getvalue(),
            "thumbnail_sample.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    if excel_file:
        try:
            df = read_excel_safe(excel_file)
            st.session_state["df"] = df
            st.success(f"✅ Đọc được **{len(df)}** sản phẩm từ file.")
            with st.expander("📋 Xem trước dữ liệu", expanded=False):
                st.dataframe(df, use_container_width=True, height=min(300, 38 * len(df) + 38))
        except Exception as e:
            st.error(f"❌ Lỗi đọc file: {e}")

    st.markdown("---")
    st.markdown("#### 🖼️ Bước 2 — Ảnh sản phẩm (bắt buộc)")
    st.caption(
        "Upload tất cả ảnh sản phẩm. Tên file cần chứa **id** của sản phẩm (VD: `SP001.png`, `SP001_main.jpg`). "
        "App sẽ tự khớp theo tên. Ảnh sẽ được auto crop/resize về 600×600 mà không làm méo."
    )
    img_files = st.file_uploader(
        "Ảnh (PNG, JPG, WEBP) - chọn nhiều cùng lúc",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
    )
    if img_files:
        st.session_state["img_files"] = img_files
        st.success(f"✅ Đã nhận **{len(img_files)}** ảnh.")

    # Matching summary
    df = st.session_state.get("df")
    imgs = st.session_state.get("img_files")
    if df is not None and imgs:
        mapping, orig_names, matched, unmatched = match_images_by_id(df, imgs)
        st.session_state["mapping"] = mapping
        st.session_state["orig_names"] = orig_names
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"<div class='stat-card'><h3>{len(df)}</h3><p>Dòng trong Excel</p></div>",
                        unsafe_allow_html=True)
        with c2:
            st.markdown(f"<div class='stat-card'><h3>{len(matched)}</h3><p>Khớp ảnh</p></div>",
                        unsafe_allow_html=True)
        with c3:
            st.markdown(f"<div class='stat-card'><h3>{len(unmatched)}</h3><p>Thiếu ảnh</p></div>",
                        unsafe_allow_html=True)
        if unmatched:
            with st.expander(f"⚠️ {len(unmatched)} sản phẩm chưa có ảnh", expanded=False):
                st.write(unmatched)


# ============ TEST ĐƠN LẺ ============
with tab_single:
    st.markdown("#### 🧪 Thử nghiệm với 1 sản phẩm")
    st.caption("Upload 1 ảnh + nhập text để xem preview tức thì. Không cần Excel.")
    cA, cB = st.columns([1, 1])
    with cA:
        single_img = st.file_uploader("Ảnh sản phẩm", type=["png", "jpg", "jpeg", "webp"], key="single")
        s_id = st.text_input("ID sản phẩm", "DEMO001")
        s_t1 = st.text_input("Text 1", "BLUETOOTH 5.4")
        s_t2 = st.text_input("Text 2", "CỔNG SẠC TYPE-C")
    with cB:
        if single_img is not None:
            try:
                prod = Image.open(single_img)
                bg = load_background()
                thumb, info = build_thumbnail(prod, s_t1, s_t2, bg, cfg)
                st.image(thumb, caption=f"Preview — {s_id}", use_container_width=True)
                meta_line = f"📐 600×600 · Font size thực: {info['font_sizes_used']}"
                if info["any_shrunk"]:
                    meta_line += " ⚡ (đã shrink)"
                st.caption(meta_line)

                fmt = out_meta["format"].lower()
                data = pil_to_bytes(thumb, fmt, out_meta["jpg_quality"])
                fname = f"{sanitize_filename(s_id)}.{fmt}"
                st.download_button(
                    "⬇️ Tải thumbnail này",
                    data, fname,
                    "image/png" if fmt == "png" else "image/jpeg",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"❌ Lỗi: {e}")
        else:
            st.info("👈 Upload 1 ảnh sản phẩm để xem preview")


# ============ PREVIEW HÀNG LOẠT ============
with tab_preview:
    df = st.session_state.get("df")
    mapping = st.session_state.get("mapping", {})
    if df is None or not mapping:
        st.info("👈 Hoàn tất bước 1 (upload Excel + ảnh) để xem preview hàng loạt.")
    else:
        st.markdown(f"#### 👁️ Preview {len(mapping)} thumbnail")
        st.caption("Mọi thay đổi ở sidebar sẽ được áp dụng tức thì. Grid hiển thị tối đa 24 thumbnail đầu.")

        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            search = st.text_input("🔍 Tìm theo ID hoặc text", "")
        with c2:
            cols_per_row = st.selectbox("Cột / hàng", [2, 3, 4, 6], index=2)
        with c3:
            max_preview = st.selectbox("Số thumbnail preview", [12, 24, 48, 100], index=1)

        df_view = df[df["id"].isin(mapping.keys())].copy()
        if search:
            s = search.lower()
            df_view = df_view[
                df_view["id"].str.lower().str.contains(s)
                | df_view["text1"].str.lower().str.contains(s)
                | df_view["text2"].str.lower().str.contains(s)
            ]

        if len(df_view) == 0:
            st.warning("Không có kết quả khớp.")
        else:
            bg = load_background()
            view_rows = df_view.head(max_preview).to_dict("records")
            with st.spinner(f"Đang tạo {len(view_rows)} preview..."):
                cols = st.columns(cols_per_row)
                for i, row in enumerate(view_rows):
                    pid = row["id"]
                    try:
                        prod = Image.open(io.BytesIO(mapping[pid]))
                        thumb, info = build_thumbnail(prod, row["text1"], row["text2"], bg, cfg)
                        with cols[i % cols_per_row]:
                            st.markdown("<div class='thumb-tile'>", unsafe_allow_html=True)
                            st.image(thumb, use_container_width=True)
                            shrunk_badge = " ⚡" if info["any_shrunk"] else ""
                            st.markdown(
                                f"<div class='thumb-id'>{pid}{shrunk_badge}</div>"
                                f"<div class='thumb-meta'>{row['text1']}"
                                + (f" · {row['text2']}" if row['text2'] else "")
                                + f"<br>font: {info['font_sizes_used']}</div>"
                                  "</div>",
                                unsafe_allow_html=True,
                            )
                    except Exception as e:
                        with cols[i % cols_per_row]:
                            st.error(f"❌ {pid}: {e}")

            if len(df_view) > max_preview:
                st.info(f"Hiện {max_preview}/{len(df_view)} kết quả. Tăng `Số thumbnail preview` nếu cần xem thêm.")


# ============ EXPORT ZIP ============
with tab_export:
    df = st.session_state.get("df")
    mapping = st.session_state.get("mapping", {})
    if df is None or not mapping:
        st.info("👈 Hoàn tất bước 1 để xuất ZIP.")
    else:
        st.markdown(f"#### 📦 Xuất {len(mapping)} thumbnail + CSV CMS")
        st.caption(
            "Khi bấm **Tạo ZIP**, app sẽ render từng thumbnail với cấu hình hiện tại, "
            "đóng gói vào file ZIP kèm **cms.csv** (id, text1, text2, filename, font_size, shrunk)."
        )

        colL, colR = st.columns([2, 1])
        with colL:
            include_csv = st.checkbox("Kèm file CSV CMS", value=True)
            include_source = st.checkbox("Kèm ảnh gốc vào thư mục `source/`", value=False,
                                         help="Tuỳ chọn: đính kèm ảnh gốc chưa xử lý để đối chiếu.")
            zip_name = st.text_input("Tên file ZIP", f"thumbnails_{time.strftime('%Y%m%d_%H%M%S')}.zip")
        with colR:
            st.markdown(
                f"""
                <div class='stat-card' style='text-align:center;'>
                    <h3>{len(mapping)}</h3>
                    <p>Thumbnail sẽ xuất · {out_meta['format']}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        if st.button("🚀 Tạo ZIP", type="primary", use_container_width=True):
            bg = load_background()
            fmt = out_meta["format"].lower()

            progress = st.progress(0.0, text="Chuẩn bị...")
            zip_buf = io.BytesIO()
            cms_rows = []
            t0 = time.time()

            df_export = df[df["id"].isin(mapping.keys())].reset_index(drop=True)
            total = len(df_export)

            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for i, row in df_export.iterrows():
                    pid = row["id"]
                    progress.progress((i + 1) / total, text=f"Đang render [{i + 1}/{total}] {pid}")
                    try:
                        prod = Image.open(io.BytesIO(mapping[pid]))
                        thumb, info = build_thumbnail(prod, row["text1"], row["text2"], bg, cfg)
                        safe_id = sanitize_filename(pid)
                        fname = f"{safe_id}.{fmt}"
                        zf.writestr(
                            f"thumbnails/{fname}",
                            pil_to_bytes(thumb, fmt, out_meta["jpg_quality"]),
                        )
                        if include_source:
                            orig_names = st.session_state.get("orig_names", {})
                            ext = Path(orig_names.get(pid, f"{pid}.png")).suffix or ".png"
                            zf.writestr(f"source/{safe_id}{ext}", mapping[pid])

                        cms_rows.append({
                            "id": pid,
                            "text1": row["text1"],
                            "text2": row["text2"],
                            "filename": fname,
                            "font_sizes_used": ";".join(str(s) for s in info["font_sizes_used"]),
                            "shrunk": "yes" if info["any_shrunk"] else "no",
                            "width": CANVAS_SIZE,
                            "height": CANVAS_SIZE,
                        })
                    except Exception as e:
                        cms_rows.append({
                            "id": pid, "text1": row["text1"], "text2": row["text2"],
                            "filename": "", "font_sizes_used": "", "shrunk": "ERROR",
                            "width": 0, "height": 0, "error": str(e),
                        })

                if include_csv:
                    cms_df = pd.DataFrame(cms_rows)
                    csv_data = cms_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                    zf.writestr("cms.csv", csv_data)

                    xbuf = io.BytesIO()
                    with pd.ExcelWriter(xbuf, engine="openpyxl") as w:
                        cms_df.to_excel(w, index=False, sheet_name="CMS")
                    zf.writestr("cms.xlsx", xbuf.getvalue())

                readme = (
                    "THUMBNAIL BUILDER PRO — EXPORT\n"
                    f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"Items: {total}\n"
                    f"Canvas: {CANVAS_SIZE}×{CANVAS_SIZE}\n"
                    f"Format: {fmt.upper()}\n\n"
                    "Folders:\n"
                    "  thumbnails/ — thumbnail 600×600 đặt tên theo id\n"
                    "  source/     — (tuỳ chọn) ảnh gốc\n"
                    "  cms.csv, cms.xlsx — CMS metadata\n"
                )
                zf.writestr("README.txt", readme)

            progress.empty()
            elapsed = time.time() - t0
            st.success(f"✅ Hoàn tất {total} thumbnail trong {elapsed:.1f}s.")

            st.download_button(
                "⬇️ TẢI FILE ZIP",
                zip_buf.getvalue(),
                zip_name,
                "application/zip",
                use_container_width=True,
            )
