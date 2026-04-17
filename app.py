"""
app.py — Thumbnail Builder Pro v5
100% Streamlit native — không HTML lộn xộn.
Sidebar hiện đầy đủ tính năng, tổ chức rõ ràng.
"""
from __future__ import annotations
import io, time, zipfile
from pathlib import Path
from typing import Dict, List
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFilter
from image_processor import (
    CANVAS_SIZE, DEFAULT_FONT_SIZE, ThumbnailConfig,
    build_thumbnail, pil_to_bytes, sanitize_filename,
)
from auth import require_login, logout_btn


def _fallback_bg(sz=600):
    bg = Image.new("RGBA", (sz, sz), (255,255,255,255))
    a = np.array(bg, dtype=np.float32)
    h = int(sz * .78)
    for c in range(3): a[h:,:,c] *= np.linspace(1,.93,sz-h)[:,None]
    bg = Image.fromarray(np.clip(a,0,255).astype(np.uint8), "RGBA")
    s = Image.new("RGBA",(sz,sz),(0,0,0,0))
    ImageDraw.Draw(s).ellipse([sz//2-210,int(sz*.82)-24,sz//2+210,int(sz*.82)+24],fill=(0,0,0,35))
    bg.alpha_composite(s.filter(ImageFilter.GaussianBlur(8)))
    return bg


# ══════════════════════════════════════
#  PAGE
# ══════════════════════════════════════
st.set_page_config(page_title="Thumbnail Builder Pro", page_icon="🖼️", layout="wide")
st.markdown("""<style>
#MainMenu,footer,header[data-testid="stToolbar"]{visibility:hidden}
.block-container{padding-top:.8rem}
</style>""", unsafe_allow_html=True)

if not require_login():
    st.stop()

_DIR = Path(__file__).resolve().parent
_ASSETS = _DIR / "assets"

@st.cache_resource(show_spinner=False)
def _bg():
    p = _ASSETS / "background.png"
    if p.exists():
        try: return Image.open(p).convert("RGBA")
        except: pass
    return _fallback_bg()


# ══════════════════════════════════════
#  SIDEBAR — đầy đủ, tổ chức đẹp
# ══════════════════════════════════════
with st.sidebar:
    st.markdown("### 🖼️ Thumbnail Builder")
    st.caption("Cấu hình thumbnail 600×600")

    st.divider()

    # ──── LAYOUT SẢN PHẨM ────
    st.markdown("**📐 Layout sản phẩm**")
    col1, col2 = st.columns(2)
    with col1:
        top_m = st.number_input("Trên → SP", 0, 300, 155, 5, help="Mặc định 155: SP nằm dưới pill")
    with col2:
        bot_m = st.number_input("Dưới → SP", 0, 250, 55, 5)

    col1, col2 = st.columns(2)
    with col1:
        side_p = st.number_input("Padding bên", 0, 100, 40, 5)
    with col2:
        prod_scale = st.number_input("Zoom SP", 0.5, 1.5, 1.0, 0.05, format="%.2f")

    center = st.radio("Căn giữa", ["Centroid", "Bbox"], horizontal=True,
                       help="Centroid: tốt cho SP bất đối xứng (chảo, ấm)")

    st.divider()

    # ──── FONT & TEXT ────
    st.markdown("**✒️ Font & Text**")
    col1, col2 = st.columns(2)
    with col1:
        font_size = st.number_input("Font size", 9.0, 30.0, 20.4, 0.2, format="%.1f")
    with col2:
        text_pad = st.number_input("Padding text", 5, 50, 25, 1)

    WEIGHTS = {"Regular":400,"Medium":500,"SemiBold":600,"Bold":700,"ExtraBold":800,"Black":900}
    col1, col2 = st.columns(2)
    with col1:
        wname = st.selectbox("Weight", list(WEIGHTS.keys()), index=4)
    with col2:
        color_hex = st.color_picker("Màu chữ", "#000000")

    font_weight = WEIGHTS[wname]
    text_color = tuple(int(color_hex[i:i+2], 16) for i in (1,3,5))

    st.divider()

    # ──── PILL & SHADOW ────
    st.markdown("**💊 Pill (khung text)**")
    col1, col2, col3 = st.columns(3)
    with col1: pill_left = st.number_input("Left", 0, 100, 8, 2)
    with col2: pill_right = st.number_input("Right", 100, 500, 300, 10)
    with col3: pill_height = st.number_input("Cao", 20, 80, 49, 2)

    col1, col2 = st.columns(2)
    with col1: pill1_top = st.number_input("Pill 1 top", 0, 100, 8, 2)
    with col2: pill2_gap = st.number_input("Khoảng cách", 0, 40, 11, 1)

    st.markdown("**🌑 Bóng đổ**")
    col1, col2 = st.columns(2)
    with col1:
        sh_x = st.number_input("X", -10, 10, 3, 1)
        sh_blur = st.number_input("Blur", 0, 20, 5, 1)
    with col2:
        sh_y = st.number_input("Y", -10, 15, 5, 1)
        sh_op = st.number_input("Opacity", 0, 255, 112, 5)

    st.divider()

    # ──── TÁCH NỀN & XUẤT ────
    st.markdown("**🪄 Tách nền & Xuất**")
    remove_bg = st.toggle("Tách nền trắng", False, help="Bật khi ảnh có nền trắng cần xóa")
    if remove_bg:
        white_tol = st.slider("Độ nhạy tách nền", 5, 40, 18)
    else:
        white_tol = 18

    show_bg_file = st.toggle("Dùng background mẫu", True, help="Tắt → nền trắng tinh")

    col1, col2 = st.columns(2)
    with col1:
        out_fmt = st.selectbox("Format", ["PNG", "JPG"])
    with col2:
        jpg_q = st.number_input("JPG quality", 70, 100, 92, disabled=(out_fmt != "JPG"))

    st.divider()
    logout_btn()


# Build config
cfg = ThumbnailConfig(
    top_margin=top_m, bottom_margin=bot_m, side_padding=side_p,
    font_size=font_size, font_weight=font_weight,
    text_color=text_color, text_padding=text_pad,
    remove_bg_mode="white" if remove_bg else "none",
    white_tolerance=white_tol,
    show_background=show_bg_file,
    center_mode="centroid" if center == "Centroid" else "bbox",
    product_scale=prod_scale,
    pill_left=pill_left, pill_right=pill_right, pill_height=pill_height,
    pill1_top=pill1_top, pill2_gap=pill2_gap,
    shadow_offset_x=sh_x, shadow_offset_y=sh_y,
    shadow_blur=sh_blur, shadow_opacity=sh_op,
)
_out_fmt = out_fmt.lower()


# ══════════════════════════════════════
#  HEADER
# ══════════════════════════════════════
h1, h2 = st.columns([4, 1])
with h1:
    st.markdown("### 🖼️ Thumbnail Builder Pro")
    st.caption("Tạo thumbnail 600×600 hàng loạt · Montserrat · Smart-fit · Auto-shrink text")
with h2:
    st.metric("Canvas", "600×600")


# ══════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════
def _read_excel(file):
    name = getattr(file, "name", "").lower()
    df = pd.read_csv(file, dtype=str, keep_default_na=False) if name.endswith(".csv") \
         else pd.read_excel(file, dtype=str, keep_default_na=False)
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
    by_stem = {}
    for f in imgs:
        by_stem[Path(f.name).stem.strip().lower()] = (f.getvalue(), f.name)
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


# ══════════════════════════════════════
#  TABS
# ══════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs(["📥 Upload", "🔬 Test nhanh", "👁️ Preview", "📦 Xuất ZIP"])


# ═══ TAB 1: UPLOAD ═══
with tab1:
    # Step 1
    st.markdown("#### 📄 Bước 1 — File Excel / CSV")
    c1, c2 = st.columns([4, 1])
    with c1:
        excel_file = st.file_uploader("Excel (id, text1, text2)", type=["xlsx","xls","csv"],
                                       help="Cột: id/sku/masp, text1/tt1/dong1, text2/tt2/dong2")
    with c2:
        st.write("")
        st.write("")
        sample = pd.DataFrame({"id":["SP001","SP002","SP003"],
                                "text1":["BLUETOOTH 5.4","CHỐNG NƯỚC IPX7","PIN 30H"],
                                "text2":["CỔNG SẠC TYPE-C","","SẠC NHANH"]})
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            sample.to_excel(w, index=False)
        st.download_button("📥 Mẫu", buf.getvalue(), "mau.xlsx", use_container_width=True)

    if excel_file:
        try:
            df = _read_excel(excel_file)
            st.session_state["df"] = df
            st.success(f"✅ {len(df)} sản phẩm")
            with st.expander("Xem dữ liệu"):
                st.dataframe(df, use_container_width=True, height=min(250, 38*len(df)+38))
        except Exception as e:
            st.error(f"Lỗi: {e}")

    st.markdown("---")

    # Step 2
    st.markdown("#### 🖼️ Bước 2 — Ảnh sản phẩm")
    st.caption("Tên file chứa id. VD: `SP001.png`, `sp001_main.jpg` — app tự khớp.")
    img_files = st.file_uploader("Ảnh SP", type=["png","jpg","jpeg","webp"],
                                  accept_multiple_files=True)
    if img_files:
        st.session_state["img_files"] = img_files

    # Match
    df = st.session_state.get("df")
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
            with st.expander(f"⚠️ {len(unmatched)} SP thiếu ảnh"):
                st.write(unmatched)


# ═══ TAB 2: TEST NHANH ═══
with tab2:
    st.markdown("#### 🔬 Test 1 sản phẩm — không cần Excel")
    c_left, c_right = st.columns([1, 1], gap="large")

    with c_left:
        single_img = st.file_uploader("Ảnh SP", type=["png","jpg","jpeg","webp"], key="single_up")
        col_a, col_b = st.columns(2)
        with col_a:
            s_id = st.text_input("ID", "DEMO001")
            s_t1 = st.text_input("Text 1", "BLUETOOTH 5.4")
        with col_b:
            st.write("")
            st.write("")
            s_t2 = st.text_input("Text 2", "CỔNG SẠC TYPE-C")

    with c_right:
        if single_img:
            try:
                prod = Image.open(single_img)
                bg = _bg()
                thumb, info = build_thumbnail(prod, s_t1, s_t2, bg, cfg)
                st.image(thumb, use_container_width=True)
                sizes = info['font_sizes_used']
                shrunk = " ⚡ shrunk" if info["any_shrunk"] else ""
                st.caption(f"600×600 · Font {sizes}{shrunk}")
                data = pil_to_bytes(thumb, _out_fmt, jpg_q)
                st.download_button(f"⬇️ Tải {s_id}.{_out_fmt}", data,
                                   f"{sanitize_filename(s_id)}.{_out_fmt}",
                                   use_container_width=True)
            except Exception as e:
                st.error(str(e))
        else:
            with st.container(border=True):
                st.markdown("<div style='text-align:center;padding:40px 0;color:#aaa;'>"
                            "<div style='font-size:36px;'>🖼️</div>"
                            "Upload ảnh bên trái để preview</div>",
                            unsafe_allow_html=True)


# ═══ TAB 3: PREVIEW ═══
with tab3:
    df = st.session_state.get("df")
    mapping = st.session_state.get("mapping", {})

    if df is None or not mapping:
        with st.container(border=True):
            st.markdown("<div style='text-align:center;padding:40px;color:#aaa;'>"
                        "<div style='font-size:36px;'>📋</div>"
                        "Hoàn tất tab Upload để preview</div>", unsafe_allow_html=True)
    else:
        c1, c2, c3 = st.columns([3, 1, 1])
        with c1:
            search = st.text_input("🔍 Tìm kiếm", "", placeholder="ID hoặc text...")
        with c2:
            cols_n = st.selectbox("Cột", [2,3,4,6], index=2)
        with c3:
            max_n = st.selectbox("Số lượng", [12,24,48,100], index=1)

        df_v = df[df["id"].isin(mapping.keys())].copy()
        if search:
            s = search.lower()
            df_v = df_v[
                df_v["id"].str.lower().str.contains(s, na=False) |
                df_v["text1"].str.lower().str.contains(s, na=False) |
                df_v["text2"].str.lower().str.contains(s, na=False)
            ]

        if len(df_v) == 0:
            st.warning("Không tìm thấy.")
        else:
            bg = _bg()
            rows = df_v.head(max_n).to_dict("records")
            prog = st.progress(0, f"Rendering {len(rows)} thumbnail...")
            cols = st.columns(cols_n)

            for i, row in enumerate(rows):
                prog.progress((i+1)/len(rows))
                pid = row["id"]
                try:
                    prod = Image.open(io.BytesIO(mapping[pid]))
                    thumb, info = build_thumbnail(prod, row["text1"], row["text2"], bg, cfg)
                    with cols[i % cols_n]:
                        with st.container(border=True):
                            st.image(thumb, use_container_width=True)
                            shrunk = " ⚡" if info["any_shrunk"] else ""
                            st.markdown(f"**{pid}**{shrunk}")
                            meta = row["text1"]
                            if row["text2"]: meta += f" · {row['text2']}"
                            st.caption(meta)
                except Exception as e:
                    with cols[i % cols_n]:
                        st.error(f"{pid}: {e}")

            prog.empty()
            if len(df_v) > max_n:
                st.info(f"Hiện {max_n}/{len(df_v)}. Tăng số lượng nếu cần.")


# ═══ TAB 4: EXPORT ═══
with tab4:
    df = st.session_state.get("df")
    mapping = st.session_state.get("mapping", {})

    if df is None or not mapping:
        with st.container(border=True):
            st.markdown("<div style='text-align:center;padding:40px;color:#aaa;'>"
                        "<div style='font-size:36px;'>📦</div>"
                        "Hoàn tất tab Upload trước</div>", unsafe_allow_html=True)
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("🖼️ Thumbnail", len(mapping))
        c2.metric("📐 Format", out_fmt)
        c3.metric("📏 Size", "600×600")

        st.markdown("")
        col1, col2 = st.columns([2, 1])
        with col1:
            include_csv = st.checkbox("📄 Kèm CMS (csv + xlsx)", True)
            include_src = st.checkbox("🗂️ Kèm ảnh gốc (source/)", False)
        with col2:
            zip_name = st.text_input("Tên ZIP", f"thumbnails_{time.strftime('%Y%m%d_%H%M')}.zip")

        st.markdown("")
        if st.button("🚀 Tạo & Tải ZIP", type="primary", use_container_width=True):
            bg = _bg()
            prog = st.progress(0, "Đang render...")
            z_buf = io.BytesIO()
            cms = []
            t0 = time.time()
            df_ex = df[df["id"].isin(mapping.keys())].reset_index(drop=True)
            total = len(df_ex)

            with zipfile.ZipFile(z_buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for i, row in df_ex.iterrows():
                    pid = row["id"]
                    prog.progress((i+1)/total, f"[{i+1}/{total}] {pid}")
                    try:
                        prod = Image.open(io.BytesIO(mapping[pid]))
                        thumb, info = build_thumbnail(prod, row["text1"], row["text2"], bg, cfg)
                        sid = sanitize_filename(pid)
                        fn = f"{sid}.{_out_fmt}"
                        zf.writestr(f"thumbnails/{fn}", pil_to_bytes(thumb, _out_fmt, jpg_q))
                        if include_src:
                            on = st.session_state.get("orig_names", {})
                            ext = Path(on.get(pid, f"{pid}.png")).suffix or ".png"
                            zf.writestr(f"source/{sid}{ext}", mapping[pid])
                        cms.append({"id":pid,"text1":row["text1"],"text2":row["text2"],
                                    "filename":fn,
                                    "fonts":";".join(str(s) for s in info["font_sizes_used"]),
                                    "shrunk":"yes" if info["any_shrunk"] else "no"})
                    except Exception as e:
                        cms.append({"id":pid,"text1":row["text1"],"text2":row["text2"],
                                    "filename":"ERROR","fonts":"","shrunk":str(e)})

                if include_csv and cms:
                    cdf = pd.DataFrame(cms)
                    zf.writestr("cms.csv", cdf.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"))
                    xb = io.BytesIO()
                    with pd.ExcelWriter(xb, engine="openpyxl") as w:
                        cdf.to_excel(w, index=False, sheet_name="CMS")
                    zf.writestr("cms.xlsx", xb.getvalue())

            prog.empty()
            st.success(f"✅ Xong {total} thumbnail — {time.time()-t0:.1f}s")
            st.download_button("⬇️ TẢI ZIP", z_buf.getvalue(), zip_name, "application/zip",
                               use_container_width=True)
