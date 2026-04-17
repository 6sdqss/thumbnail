"""
app.py — Thumbnail Builder Pro v3
UI nâng cấp toàn diện, giữ nguyên 100% logic.
"""
from __future__ import annotations
import io, os, time, zipfile
from pathlib import Path
from typing import Dict, List, Tuple
import pandas as pd
import streamlit as st
from PIL import Image
from auth import logout_button, require_login
from image_processor import (
    CANVAS_SIZE, DEFAULT_FONT_SIZE, ThumbnailConfig,
    build_thumbnail, pil_to_bytes, sanitize_filename,
)

# Fallback background nếu thiếu file assets/background.png
def generate_default_background(size=600):
    from PIL import ImageDraw, ImageFilter
    import numpy as np
    bg = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    arr = np.array(bg).astype(np.float32)
    horizon_y = int(size * 0.78)
    shadow = np.linspace(1.0, 0.93, size - horizon_y)
    for c in range(3):
        arr[horizon_y:, :, c] *= shadow[:, None]
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    bg = Image.fromarray(arr, "RGBA")
    sl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sl)
    cx, cy = size // 2, int(size * 0.82)
    sd.ellipse([cx - 210, cy - 24, cx + 210, cy + 24], fill=(0, 0, 0, 35))
    sl = sl.filter(ImageFilter.GaussianBlur(radius=8))
    bg.alpha_composite(sl)
    return bg

# ═══════ PAGE CONFIG ═══════
st.set_page_config(
    page_title="Thumbnail Builder Pro",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════ GLOBAL CSS ═══════
st.markdown("""
<style>
  /* === Hide Streamlit defaults === */
  #MainMenu, footer, header [data-testid="stToolbar"] {visibility:hidden;}
  .block-container {padding:1rem 1.5rem 2rem; max-width:1440px;}

  /* === Typography === */
  h1,h2,h3,h4 {font-weight:700 !important; letter-spacing:-0.3px;}

  /* === Top Banner === */
  .top-banner {
    background:linear-gradient(135deg,#4f46e5 0%,#7c3aed 50%,#6d28d9 100%);
    color:#fff; border-radius:16px; padding:20px 28px; margin-bottom:20px;
    display:flex; align-items:center; justify-content:space-between; gap:16px;
    box-shadow:0 4px 20px rgba(79,70,229,.25);
  }
  .top-banner h2 {color:#fff !important; margin:0; font-size:22px;}
  .top-banner p {color:rgba(255,255,255,.85); margin:2px 0 0; font-size:13px;}
  .top-banner .badge {
    background:rgba(255,255,255,.18); border-radius:8px; padding:6px 14px;
    font-size:11px; color:#fff; backdrop-filter:blur(4px); white-space:nowrap;
  }

  /* === Stat Cards === */
  .metric-row {display:flex; gap:12px; margin:12px 0 16px;}
  .metric-card {
    flex:1; background:#fff; border:1px solid #e5e7eb; border-radius:14px;
    padding:16px 18px; text-align:center; transition:all .15s;
    box-shadow:0 1px 3px rgba(0,0,0,.04);
  }
  .metric-card:hover {border-color:#a5b4fc; box-shadow:0 4px 12px rgba(79,70,229,.1);}
  .metric-val {font-size:28px; font-weight:800; color:#4f46e5; line-height:1.1;}
  .metric-label {font-size:12px; color:#6b7280; margin-top:4px;}

  /* === Preview Grid Tiles === */
  .preview-tile {
    background:#fff; border:1px solid #e5e7eb; border-radius:14px;
    padding:8px; margin-bottom:12px; transition:all .2s;
    box-shadow:0 1px 3px rgba(0,0,0,.04);
  }
  .preview-tile:hover {transform:translateY(-2px); box-shadow:0 8px 20px rgba(0,0,0,.08);}
  .preview-tile img {border-radius:10px; width:100%; display:block;}
  .tile-id {font-weight:700; font-size:13px; color:#111827; margin-top:6px; padding:0 4px;}
  .tile-meta {font-size:11px; color:#9ca3af; padding:0 4px 4px;}

  /* === Upload Zone === */
  [data-testid="stFileUploader"] {
    border:2px dashed #d1d5db !important; border-radius:14px !important;
    transition:border-color .2s;
  }
  [data-testid="stFileUploader"]:hover {border-color:#818cf8 !important;}

  /* === Buttons === */
  .stButton>button {border-radius:10px !important; font-weight:600 !important; transition:all .15s !important;}
  .stDownloadButton>button {
    border-radius:10px !important; font-weight:700 !important;
    background:linear-gradient(135deg,#4f46e5,#7c3aed) !important;
    color:#fff !important; border:none !important;
  }
  .stDownloadButton>button:hover {opacity:.9 !important; transform:translateY(-1px);}

  /* === Sidebar polish === */
  [data-testid="stSidebar"] {background:#fafbfd;}
  [data-testid="stSidebar"] .stSlider label {font-size:13px;}

  /* === Tab bar === */
  .stTabs [data-baseweb="tab-list"] {gap:4px; border-bottom:2px solid #f1f5f9;}
  .stTabs [data-baseweb="tab"] {
    font-weight:600; font-size:13px; border-radius:8px 8px 0 0;
    padding:8px 16px;
  }

  /* === Step indicators === */
  .step-badge {
    display:inline-block; background:#4f46e5; color:#fff; font-size:11px;
    font-weight:700; width:22px; height:22px; line-height:22px;
    text-align:center; border-radius:50%; margin-right:8px;
  }

  /* === Tip box === */
  .tip-box {
    background:linear-gradient(135deg,#f0f9ff,#eff6ff); border:1px solid #bfdbfe;
    border-radius:12px; padding:12px 16px; font-size:13px; color:#1e40af;
    margin:8px 0;
  }
  .tip-box b {color:#1e3a8a;}

  /* === Section dividers === */
  .section-label {
    font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:1px;
    color:#9ca3af; margin:20px 0 8px; padding-left:2px;
  }
</style>
""", unsafe_allow_html=True)

# ═══════ LOGIN ═══════
if not require_login():
    st.stop()

# ═══════ PATHS ═══════
_APP_DIR = Path(__file__).resolve().parent
ASSETS_DIR = _APP_DIR / "assets"
FONTS_DIR = _APP_DIR / "fonts"

# ═══════ HELPERS ═══════
@st.cache_resource(show_spinner=False)
def load_background() -> Image.Image:
    bg_path = ASSETS_DIR / "background.png"
    if bg_path.exists():
        try: return Image.open(bg_path).convert("RGBA")
        except Exception: pass
    return generate_default_background(600)


def read_excel_safe(file) -> pd.DataFrame:
    name = getattr(file, "name", "").lower()
    df = pd.read_csv(file, dtype=str, keep_default_na=False) if name.endswith(".csv") \
         else pd.read_excel(file, dtype=str, keep_default_na=False)
    df.columns = [str(c).strip().lower().replace(" ", "") for c in df.columns]
    col_map = {}
    for c in df.columns:
        if c in ("id","sku","masp","ma","productid","code"): col_map[c] = "id"
        elif c in ("text1","tt1","dong1","line1","title1"): col_map[c] = "text1"
        elif c in ("text2","tt2","dong2","line2","title2"): col_map[c] = "text2"
    df = df.rename(columns=col_map)
    for col in ("id","text1","text2"):
        if col not in df.columns: df[col] = ""
    df = df[["id","text1","text2"]].copy()
    for col in df.columns: df[col] = df[col].astype(str).str.strip()
    return df[df["id"] != ""].reset_index(drop=True)


def match_images_by_id(df, uploaded_images):
    img_by_stem = {}
    for f in uploaded_images:
        stem = Path(f.name).stem.strip().lower()
        img_by_stem[stem] = (f.getvalue(), f.name)
    mapping, orig_names, matched, unmatched = {}, {}, [], []
    for pid in df["id"].tolist():
        key = str(pid).strip().lower()
        hit = img_by_stem.get(key)
        if not hit:
            for stem, data_name in img_by_stem.items():
                if key in stem or stem in key: hit = data_name; break
        if hit:
            mapping[pid] = hit[0]; orig_names[pid] = hit[1]; matched.append(pid)
        else:
            unmatched.append(pid)
    return mapping, orig_names, matched, unmatched


# ═══════ SIDEBAR CONFIG ═══════
def build_config_from_sidebar():
    with st.sidebar:
        st.markdown("## ⚙️ Cấu hình")

        # --- Product Layout ---
        st.markdown("<div class='section-label'>📐 Layout sản phẩm</div>", unsafe_allow_html=True)
        top_m = st.slider("Khoảng trên → SP", 0, 300, 155, help="Mặc định 155 — SP dưới pill")
        bot_m = st.slider("Khoảng dưới → SP", 0, 250, 55)
        side_p = st.slider("Padding 2 bên", 0, 100, 40)

        c1, c2 = st.columns(2)
        with c1:
            center_mode = st.radio("Căn giữa", ["Centroid", "Bbox"], index=0, label_visibility="collapsed")
        with c2:
            prod_scale = st.slider("Zoom", 0.5, 1.3, 1.0, 0.05, label_visibility="collapsed")
        center_mode = "centroid" if center_mode == "Centroid" else "bbox"

        # --- Text & Font ---
        st.markdown("<div class='section-label'>✒️ Text & Font</div>", unsafe_allow_html=True)
        font_size = st.slider("Font size", 9.0, 30.0, 20.4, 0.1)
        text_pad = st.slider("Text padding (pill)", 10, 50, 25)

        weight_opts = {"Regular":400,"Medium":500,"SemiBold":600,"Bold":700,"ExtraBold":800,"Black":900}
        weight_name = st.select_slider("Weight", list(weight_opts.keys()), "ExtraBold")
        font_weight = weight_opts[weight_name]

        color_hex = st.color_picker("Màu chữ", "#000000")
        text_color = tuple(int(color_hex[i:i+2], 16) for i in (1, 3, 5))

        # --- Pill ---
        with st.expander("🎨 Pill & Shadow", expanded=False):
            pill_left = st.slider("Left", 0, 100, 8)
            pill_right = st.slider("Right", 150, 500, 300)
            pill_height = st.slider("Height", 30, 80, 49)
            pill1_top = st.slider("Pill 1 top", 0, 100, 8)
            pill2_gap = st.slider("Gap 2 pill", 0, 40, 11)
            sh_x = st.slider("Shadow X", -10, 10, 2)
            sh_y = st.slider("Shadow Y", -10, 15, 3)
            sh_blur = st.slider("Shadow blur", 0, 20, 6)
            sh_op = st.slider("Shadow opacity", 0, 255, 110)

        # --- Background removal ---
        with st.expander("🪄 Tách nền", expanded=False):
            bg_mode = st.radio("Mode", ["Không tách","Tách nền trắng"], index=0, horizontal=True)
            bg_mode = "none" if bg_mode == "Không tách" else "white"
            white_tol = st.slider("Độ nhạy", 5, 40, 18, disabled=(bg_mode=="none"))
            show_bg = st.checkbox("Dùng background mẫu", value=True)

        # --- Export ---
        st.markdown("<div class='section-label'>📤 Xuất file</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1: out_format = st.radio("Format", ["PNG","JPG"], horizontal=True, label_visibility="collapsed")
        with c2: jpg_quality = st.slider("Quality", 70, 100, 92, disabled=(out_format != "JPG"), label_visibility="collapsed")

        st.divider()
        logout_button()

    cfg = ThumbnailConfig(
        top_margin=top_m, bottom_margin=bot_m, side_padding=side_p,
        font_size=font_size, font_weight=font_weight,
        text_color=text_color, text_padding=text_pad,
        remove_bg_mode=bg_mode, white_tolerance=white_tol,
        show_background=show_bg, center_mode=center_mode, product_scale=prod_scale,
        pill_left=pill_left, pill_right=pill_right, pill_height=pill_height,
        pill1_top=pill1_top, pill2_gap=pill2_gap,
        shadow_offset_x=sh_x, shadow_offset_y=sh_y,
        shadow_blur=sh_blur, shadow_opacity=sh_op,
    )
    return cfg, {"format": out_format, "jpg_quality": jpg_quality}


# ═══════ TOP BANNER ═══════
st.markdown("""
<div class='top-banner'>
  <div>
    <h2>🖼️ Thumbnail Builder Pro</h2>
    <p>Tạo thumbnail 600×600 hàng loạt · Smart-fit · Auto-shrink text · Montserrat</p>
  </div>
  <div style='display:flex;gap:8px;flex-wrap:wrap;'>
    <div class='badge'>600×600</div>
    <div class='badge'>Auto text</div>
    <div class='badge'>Centroid</div>
  </div>
</div>
""", unsafe_allow_html=True)

cfg, out_meta = build_config_from_sidebar()

# ═══════ TABS ═══════
tab1, tab2, tab3, tab4 = st.tabs([
    "📥  Upload", "🔬  Test nhanh", "👁️  Preview", "📦  Xuất ZIP"
])

# ──── TAB 1: UPLOAD ────
with tab1:
    st.markdown("""
    <div class='tip-box'>
      <b>Quy trình:</b> Upload Excel (id, text1, text2) → Upload ảnh (tên chứa id) → Preview → Xuất ZIP
    </div>
    """, unsafe_allow_html=True)

    # Step 1: Excel
    st.markdown("<span class='step-badge'>1</span> **File Excel / CSV**", unsafe_allow_html=True)
    c1, c2 = st.columns([3, 1])
    with c1:
        excel_file = st.file_uploader(
            "Excel", type=["xlsx","xls","csv"], label_visibility="collapsed",
            help="Cột: id (hoặc sku/masp), text1 (hoặc tt1/dong1), text2"
        )
    with c2:
        sample = pd.DataFrame({
            "id": ["SP001","SP002","SP003"],
            "text1": ["BLUETOOTH 5.4","CHỐNG NƯỚC IPX7","PIN 30H"],
            "text2": ["CỔNG SẠC TYPE-C","","SẠC NHANH"],
        })
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            sample.to_excel(w, index=False, sheet_name="Products")
        st.download_button("📥 Tải mẫu", buf.getvalue(), "mau.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)

    if excel_file:
        try:
            df = read_excel_safe(excel_file)
            st.session_state["df"] = df
            st.success(f"Đọc **{len(df)}** sản phẩm")
            with st.expander("Xem dữ liệu", expanded=False):
                st.dataframe(df, use_container_width=True, height=min(260, 38*len(df)+38))
        except Exception as e:
            st.error(f"Lỗi đọc file: {e}")

    # Step 2: Images
    st.markdown("---")
    st.markdown("<span class='step-badge'>2</span> **Ảnh sản phẩm**", unsafe_allow_html=True)
    st.caption("Tên file chứa id sản phẩm. VD: `SP001.png`, `sp001_main.jpg`")

    img_files = st.file_uploader(
        "Ảnh", type=["png","jpg","jpeg","webp"],
        accept_multiple_files=True, label_visibility="collapsed"
    )
    if img_files:
        st.session_state["img_files"] = img_files

    # Matching
    df = st.session_state.get("df")
    imgs = st.session_state.get("img_files")
    if df is not None and imgs:
        mapping, orig_names, matched, unmatched = match_images_by_id(df, imgs)
        st.session_state["mapping"] = mapping
        st.session_state["orig_names"] = orig_names

        st.markdown(f"""
        <div class='metric-row'>
          <div class='metric-card'>
            <div class='metric-val'>{len(df)}</div>
            <div class='metric-label'>Trong Excel</div>
          </div>
          <div class='metric-card'>
            <div class='metric-val' style='color:#059669;'>{len(matched)}</div>
            <div class='metric-label'>Đã khớp ảnh</div>
          </div>
          <div class='metric-card'>
            <div class='metric-val' style='color:#dc2626;'>{len(unmatched)}</div>
            <div class='metric-label'>Thiếu ảnh</div>
          </div>
          <div class='metric-card'>
            <div class='metric-val' style='color:#7c3aed;'>{len(imgs)}</div>
            <div class='metric-label'>Ảnh upload</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        if unmatched:
            with st.expander(f"⚠️ {len(unmatched)} SP chưa khớp ảnh"):
                st.write(unmatched)


# ──── TAB 2: TEST NHANH ────
with tab2:
    st.markdown("<span class='step-badge'>⚡</span> **Test 1 ảnh nhanh** — không cần Excel", unsafe_allow_html=True)

    cA, cB = st.columns([1, 1], gap="large")
    with cA:
        single_img = st.file_uploader("Ảnh", type=["png","jpg","jpeg","webp"], key="single", label_visibility="collapsed")
        s_id = st.text_input("ID", "DEMO001")
        c1, c2 = st.columns(2)
        with c1: s_t1 = st.text_input("Text 1", "BLUETOOTH 5.4")
        with c2: s_t2 = st.text_input("Text 2", "CỔNG SẠC TYPE-C")

    with cB:
        if single_img is not None:
            try:
                prod = Image.open(single_img)
                bg = load_background()
                thumb, info = build_thumbnail(prod, s_t1, s_t2, bg, cfg)
                st.image(thumb, use_container_width=True)

                # Info bar
                sizes = info['font_sizes_used']
                shrunk = "⚡ shrunk" if info["any_shrunk"] else "✓ giữ nguyên"
                st.caption(f"📐 600×600 · Font: {sizes} · {shrunk}")

                fmt = out_meta["format"].lower()
                data = pil_to_bytes(thumb, fmt, out_meta["jpg_quality"])
                st.download_button(
                    f"⬇️ Tải {s_id}.{fmt}", data, f"{sanitize_filename(s_id)}.{fmt}",
                    "image/png" if fmt == "png" else "image/jpeg",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"Lỗi: {e}")
        else:
            st.markdown("""
            <div style='display:flex;align-items:center;justify-content:center;
                        height:300px;border:2px dashed #e5e7eb;border-radius:16px;
                        color:#9ca3af;font-size:14px;text-align:center;'>
              <div>
                <div style='font-size:40px;margin-bottom:8px;'>🖼️</div>
                Upload ảnh bên trái<br>để xem preview
              </div>
            </div>
            """, unsafe_allow_html=True)


# ──── TAB 3: PREVIEW ────
with tab3:
    df = st.session_state.get("df")
    mapping = st.session_state.get("mapping", {})

    if df is None or not mapping:
        st.markdown("""
        <div style='text-align:center;padding:60px 20px;color:#9ca3af;'>
          <div style='font-size:48px;margin-bottom:12px;'>📋</div>
          <div style='font-size:16px;font-weight:600;color:#6b7280;'>Chưa có dữ liệu</div>
          <div style='font-size:13px;margin-top:4px;'>Hoàn tất tab Upload (Excel + ảnh) để xem preview</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Controls bar
        c1, c2, c3 = st.columns([3, 1, 1])
        with c1:
            search = st.text_input("🔍 Tìm kiếm", "", placeholder="ID hoặc text...", label_visibility="collapsed")
        with c2:
            cols_per_row = st.selectbox("Cột", [2,3,4,6], index=2, label_visibility="collapsed")
        with c3:
            max_preview = st.selectbox("Hiện", [12,24,48,100], index=1, label_visibility="collapsed")

        df_view = df[df["id"].isin(mapping.keys())].copy()
        if search:
            s = search.lower()
            df_view = df_view[
                df_view["id"].str.lower().str.contains(s, na=False) |
                df_view["text1"].str.lower().str.contains(s, na=False) |
                df_view["text2"].str.lower().str.contains(s, na=False)
            ]

        if len(df_view) == 0:
            st.warning("Không tìm thấy kết quả.")
        else:
            bg = load_background()
            rows = df_view.head(max_preview).to_dict("records")

            progress_bar = st.progress(0, text=f"Rendering {len(rows)} thumbnail...")
            cols = st.columns(cols_per_row)

            for i, row in enumerate(rows):
                progress_bar.progress((i + 1) / len(rows))
                pid = row["id"]
                try:
                    prod = Image.open(io.BytesIO(mapping[pid]))
                    thumb, info = build_thumbnail(prod, row["text1"], row["text2"], bg, cfg)
                    with cols[i % cols_per_row]:
                        st.markdown("<div class='preview-tile'>", unsafe_allow_html=True)
                        st.image(thumb, use_container_width=True)
                        shrunk = " ⚡" if info["any_shrunk"] else ""
                        meta_text = row["text1"]
                        if row["text2"]: meta_text += f" · {row['text2']}"
                        st.markdown(
                            f"<div class='tile-id'>{pid}{shrunk}</div>"
                            f"<div class='tile-meta'>{meta_text}</div>"
                            "</div>",
                            unsafe_allow_html=True,
                        )
                except Exception as e:
                    with cols[i % cols_per_row]:
                        st.error(f"{pid}: {e}")

            progress_bar.empty()

            if len(df_view) > max_preview:
                st.info(f"Hiện {max_preview}/{len(df_view)}. Tăng số lượng để xem thêm.")


# ──── TAB 4: EXPORT ZIP ────
with tab4:
    df = st.session_state.get("df")
    mapping = st.session_state.get("mapping", {})

    if df is None or not mapping:
        st.markdown("""
        <div style='text-align:center;padding:60px 20px;color:#9ca3af;'>
          <div style='font-size:48px;margin-bottom:12px;'>📦</div>
          <div style='font-size:16px;font-weight:600;color:#6b7280;'>Sẵn sàng xuất</div>
          <div style='font-size:13px;margin-top:4px;'>Hoàn tất tab Upload trước</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Export summary
        st.markdown(f"""
        <div class='metric-row'>
          <div class='metric-card'>
            <div class='metric-val'>{len(mapping)}</div>
            <div class='metric-label'>Thumbnail sẽ xuất</div>
          </div>
          <div class='metric-card'>
            <div class='metric-val'>{out_meta['format']}</div>
            <div class='metric-label'>Định dạng</div>
          </div>
          <div class='metric-card'>
            <div class='metric-val'>600²</div>
            <div class='metric-label'>Kích thước (px)</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        c1, c2 = st.columns([2, 1])
        with c1:
            include_csv = st.checkbox("📄 Kèm CMS (csv + xlsx)", value=True)
            include_source = st.checkbox("🗂️ Kèm ảnh gốc (`source/`)", value=False)
        with c2:
            zip_name = st.text_input("Tên ZIP", f"thumbnails_{time.strftime('%Y%m%d_%H%M')}.zip",
                                     label_visibility="collapsed")

        if st.button("🚀 Tạo & Tải ZIP", type="primary", use_container_width=True):
            bg = load_background()
            fmt = out_meta["format"].lower()
            progress = st.progress(0, text="Đang render...")
            zip_buf = io.BytesIO()
            cms_rows = []
            t0 = time.time()
            df_export = df[df["id"].isin(mapping.keys())].reset_index(drop=True)
            total = len(df_export)

            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for i, row in df_export.iterrows():
                    pid = row["id"]
                    progress.progress((i + 1) / total, text=f"[{i+1}/{total}] {pid}")
                    try:
                        prod = Image.open(io.BytesIO(mapping[pid]))
                        thumb, info = build_thumbnail(prod, row["text1"], row["text2"], bg, cfg)
                        safe_id = sanitize_filename(pid)
                        fname = f"{safe_id}.{fmt}"
                        zf.writestr(f"thumbnails/{fname}", pil_to_bytes(thumb, fmt, out_meta["jpg_quality"]))

                        if include_source:
                            o = st.session_state.get("orig_names", {})
                            ext = Path(o.get(pid, f"{pid}.png")).suffix or ".png"
                            zf.writestr(f"source/{safe_id}{ext}", mapping[pid])

                        cms_rows.append({
                            "id": pid, "text1": row["text1"], "text2": row["text2"],
                            "filename": fname,
                            "font_sizes": ";".join(str(s) for s in info["font_sizes_used"]),
                            "shrunk": "yes" if info["any_shrunk"] else "no",
                        })
                    except Exception as e:
                        cms_rows.append({
                            "id": pid, "text1": row["text1"], "text2": row["text2"],
                            "filename": "ERROR", "font_sizes": "", "shrunk": str(e),
                        })

                if include_csv and cms_rows:
                    cms_df = pd.DataFrame(cms_rows)
                    zf.writestr("cms.csv", cms_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"))
                    xbuf = io.BytesIO()
                    with pd.ExcelWriter(xbuf, engine="openpyxl") as w:
                        cms_df.to_excel(w, index=False, sheet_name="CMS")
                    zf.writestr("cms.xlsx", xbuf.getvalue())

            progress.empty()
            st.success(f"✅ Xong {total} thumbnail — {time.time()-t0:.1f}s")
            st.download_button(
                "⬇️ TẢI ZIP", zip_buf.getvalue(), zip_name, "application/zip",
                use_container_width=True,
            )
