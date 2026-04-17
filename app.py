"""
app.py — Thumbnail Builder Pro v6
══════════════════════════════════
✓ Fix cứng Pill/Shadow (không hiện slider lộn xộn)
✓ Chỉnh TẤT CẢ hoặc TỪNG TẤM riêng lẻ
✓ Preset nhanh theo loại sản phẩm (chảo, tai nghe, chai lọ...)
✓ Bulk edit text trực tiếp trong bảng
✓ Export PNG / JPG / WebP
✓ Fix overlap toolbar Streamlit
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
    CANVAS_SIZE, ThumbnailConfig, build_thumbnail,
    pil_to_bytes, sanitize_filename,
)
from auth import require_login, logout_btn


# ═══════════════════════════════════════════════════════════════
# FIXED VALUES — đã tối ưu, không cho user chỉnh để UI gọn
# ═══════════════════════════════════════════════════════════════
PILL_LEFT     = 20
PILL_RIGHT    = 300
PILL_HEIGHT   = 49
PILL1_TOP     = 8
PILL2_GAP     = 11
SHADOW_X      = 3
SHADOW_Y      = 5
SHADOW_BLUR   = 5
SHADOW_OP     = 112
TEXT_PADDING  = 25
FONT_WEIGHT   = 800           # ExtraBold — khớp thumb mẫu
WHITE_TOL     = 18


def _fallback_bg(sz=600):
    bg = Image.new("RGBA", (sz, sz), (255, 255, 255, 255))
    a = np.array(bg, dtype=np.float32)
    h = int(sz * .78)
    for c in range(3): a[h:, :, c] *= np.linspace(1, .93, sz - h)[:, None]
    bg = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")
    s = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    ImageDraw.Draw(s).ellipse(
        [sz//2 - 210, int(sz*.82) - 24, sz//2 + 210, int(sz*.82) + 24],
        fill=(0, 0, 0, 35)
    )
    bg.alpha_composite(s.filter(ImageFilter.GaussianBlur(8)))
    return bg


# ═══════════════════════════════════════════════════════════════
# PAGE CONFIG & CSS
# ═══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Thumbnail Builder Pro",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  /* Fix overlap với toolbar Streamlit */
  .block-container{padding-top:4.5rem !important; max-width:1500px;}
  #MainMenu, footer{visibility:hidden;}

  /* Hero card */
  [data-testid="stVerticalBlock"] .hero-title{
    background:linear-gradient(135deg,#667eea,#764ba2,#f093fb);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
    font-size:32px; font-weight:900; letter-spacing:-0.8px; margin:0;
  }

  /* Buttons */
  .stButton>button{border-radius:10px !important; font-weight:600 !important;}
  .stButton>button[kind="primary"]{
    background:linear-gradient(135deg,#667eea,#764ba2) !important;
    border:none !important;
  }
  .stDownloadButton>button{
    border-radius:10px !important; font-weight:700 !important;
    background:linear-gradient(135deg,#10b981,#059669) !important;
    color:#fff !important; border:none !important;
  }

  /* Tabs */
  .stTabs [data-baseweb="tab-list"]{gap:4px;}
  .stTabs [data-baseweb="tab"]{font-weight:700; font-size:13px; padding:10px 18px;}

  /* Sidebar */
  section[data-testid="stSidebar"]{background:#fafbfd;}

  /* Metric cards */
  [data-testid="stMetric"]{
    background:#fff; border:1px solid #e5e7eb; border-radius:12px;
    padding:14px 18px; box-shadow:0 1px 3px rgba(0,0,0,.04);
  }
  [data-testid="stMetricValue"]{font-size:26px !important; font-weight:800 !important;}

  /* File uploader */
  [data-testid="stFileUploader"] section{
    border:2px dashed #c7d2fe !important; background:#faf5ff !important; border-radius:12px !important;
  }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
# LOGIN
# ═══════════════════════════════════════════════════════════════
if not require_login():
    st.stop()


# ═══════════════════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════════════════
_DIR = Path(__file__).resolve().parent
_ASSETS = _DIR / "assets"


@st.cache_resource(show_spinner=False)
def _bg():
    p = _ASSETS / "background.png"
    if p.exists():
        try: return Image.open(p).convert("RGBA")
        except Exception: pass
    return _fallback_bg()


# ═══════════════════════════════════════════════════════════════
# PRESETS
# ═══════════════════════════════════════════════════════════════
PRESETS: Dict[str, dict] = {
    "🎯 Chuẩn (mặc định)": dict(
        top_margin=155, bottom_margin=55, side_padding=40,
        product_scale=1.0, center_mode="centroid", font_size=20.4,
    ),
    "🍳 Đồ gia dụng": dict(
        top_margin=170, bottom_margin=50, side_padding=50,
        product_scale=1.1, center_mode="centroid", font_size=20.4,
    ),
    "🎧 Điện tử": dict(
        top_margin=160, bottom_margin=60, side_padding=40,
        product_scale=1.0, center_mode="centroid", font_size=20.0,
    ),
    "🧴 Mỹ phẩm, chai": dict(
        top_margin=150, bottom_margin=55, side_padding=60,
        product_scale=0.95, center_mode="bbox", font_size=20.4,
    ),
    "👕 Thời trang": dict(
        top_margin=155, bottom_margin=45, side_padding=35,
        product_scale=1.05, center_mode="bbox", font_size=20.4,
    ),
    "📱 Điện thoại dọc": dict(
        top_margin=160, bottom_margin=50, side_padding=70,
        product_scale=1.0, center_mode="bbox", font_size=20.4,
    ),
}


# Khởi tạo session state
def _init_state():
    if "preset_name" not in st.session_state:
        st.session_state["preset_name"] = "🎯 Chuẩn (mặc định)"
    if "overrides" not in st.session_state:
        # overrides[pid] = {font_size, scale, top, bot, side, center, t1, t2}
        st.session_state["overrides"] = {}
    # Áp preset mặc định nếu chưa có
    p = PRESETS[st.session_state["preset_name"]]
    for k, v in p.items():
        st.session_state.setdefault(f"cfg_{k}", v)

_init_state()


def _apply_preset(name: str):
    if name not in PRESETS: return
    p = PRESETS[name]
    for k, v in p.items():
        st.session_state[f"cfg_{k}"] = v
    st.session_state["preset_name"] = name


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════
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


def _effective_df() -> pd.DataFrame:
    """df sau khi áp override text (nếu user đã sửa trong bulk edit)."""
    df = st.session_state.get("df")
    if df is None: return pd.DataFrame()
    df = df.copy()
    ov = st.session_state.get("overrides", {})
    for pid, o in ov.items():
        mask = df["id"] == pid
        if o.get("t1") is not None: df.loc[mask, "text1"] = o["t1"]
        if o.get("t2") is not None: df.loc[mask, "text2"] = o["t2"]
    return df


def _build_config_for(pid: str | None = None) -> ThumbnailConfig:
    """Build config. Nếu pid có override → merge override lên global."""
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
        top_margin=g["top_margin"],
        bottom_margin=g["bottom_margin"],
        side_padding=g["side_padding"],
        font_size=g["font_size"],
        font_weight=FONT_WEIGHT,
        text_color=(0, 0, 0),
        text_padding=TEXT_PADDING,
        remove_bg_mode="white" if st.session_state.get("remove_bg", False) else "none",
        white_tolerance=WHITE_TOL,
        show_background=True,
        center_mode=g["center_mode"],
        product_scale=g["product_scale"],
        pill_left=PILL_LEFT, pill_right=PILL_RIGHT, pill_height=PILL_HEIGHT,
        pill1_top=PILL1_TOP, pill2_gap=PILL2_GAP,
        shadow_offset_x=SHADOW_X, shadow_offset_y=SHADOW_Y,
        shadow_blur=SHADOW_BLUR, shadow_opacity=SHADOW_OP,
    )


# ═══════════════════════════════════════════════════════════════
# SIDEBAR — gọn, chỉ thứ cần thiết
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 🖼️ Thumbnail Builder")
    st.caption("Cấu hình cho TẤT CẢ thumbnail")

    st.divider()

    # Preset
    st.markdown("**🎨 Preset nhanh**")
    sel = st.selectbox(
        "Chọn loại sản phẩm",
        list(PRESETS.keys()),
        index=list(PRESETS.keys()).index(st.session_state["preset_name"]),
        label_visibility="collapsed",
    )
    if sel != st.session_state["preset_name"]:
        _apply_preset(sel)
        st.rerun()

    st.divider()

    # Tinh chỉnh chính
    st.markdown("**📐 Layout**")
    c1, c2 = st.columns(2)
    with c1:
        st.number_input("Mép trên", 0, 300, key="cfg_top_margin", step=5)
    with c2:
        st.number_input("Mép dưới", 0, 250, key="cfg_bottom_margin", step=5)
    c1, c2 = st.columns(2)
    with c1:
        st.number_input("Padding bên", 0, 100, key="cfg_side_padding", step=5)
    with c2:
        st.number_input("Zoom SP", 0.5, 1.5, key="cfg_product_scale",
                        step=0.05, format="%.2f")
    st.radio("Căn giữa", ["centroid", "bbox"], key="cfg_center_mode",
             horizontal=True, format_func=lambda x: "Trọng tâm" if x == "centroid" else "Khung")

    st.divider()

    st.markdown("**✒️ Font**")
    st.number_input("Kích thước", 9.0, 30.0, key="cfg_font_size",
                    step=0.2, format="%.1f")

    st.divider()

    st.markdown("**📤 Xuất file**")
    st.toggle("Tách nền trắng", key="remove_bg",
              help="Bật khi ảnh SP có nền trắng cần xoá")
    out_fmt = st.selectbox("Định dạng", ["PNG", "JPG", "WEBP"])
    jpg_q = 92
    if out_fmt in ("JPG", "WEBP"):
        jpg_q = st.slider("Chất lượng", 70, 100, 92)

    st.divider()
    logout_btn()


# ═══════════════════════════════════════════════════════════════
# HERO HEADER — không overlap
# ═══════════════════════════════════════════════════════════════
with st.container():
    c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
    with c1:
        st.markdown('<h1 class="hero-title">🖼️ Thumbnail Builder Pro</h1>',
                    unsafe_allow_html=True)
        st.caption("Tạo thumbnail 600×600 hàng loạt · Smart-fit · Auto-shrink text · Montserrat")
    df = st.session_state.get("df")
    mapping = st.session_state.get("mapping", {})
    ov_count = len(st.session_state.get("overrides", {}))
    with c2:
        st.metric("📋 Excel", len(df) if df is not None else 0)
    with c3:
        st.metric("✅ Khớp ảnh", len(mapping))
    with c4:
        st.metric("🎯 Tuỳ chỉnh", ov_count)


# ═══════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════
tab_up, tab_single, tab_preview, tab_edit, tab_export = st.tabs([
    "📥 Upload",
    "🔬 Test nhanh",
    "👁️ Preview tất cả",
    "✏️ Chỉnh từng tấm",
    "📦 Xuất ZIP",
])


# ─────── TAB UPLOAD ───────
with tab_up:
    st.markdown("### 📄 Bước 1 — File Excel / CSV")

    c1, c2 = st.columns([4, 1])
    with c1:
        excel_file = st.file_uploader(
            "File Excel/CSV", type=["xlsx", "xls", "csv"],
            label_visibility="collapsed",
            help="Cột cần có: id (hoặc sku/masp), text1, text2",
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
            df = _read_excel(excel_file)
            st.session_state["df"] = df
            st.success(f"✅ Đọc được **{len(df)}** sản phẩm")
        except Exception as e:
            st.error(f"Lỗi: {e}")

    df = st.session_state.get("df")
    if df is not None:
        st.markdown("#### 📝 Chỉnh text trực tiếp (tuỳ chọn)")
        st.caption("Sửa text1 / text2 ngay tại đây nếu muốn thay đổi trước khi xuất — không cần sửa Excel lại.")

        edited = st.data_editor(
            df.copy(), use_container_width=True,
            hide_index=True, num_rows="fixed", key="bulk_editor",
            disabled=["id"],
            column_config={
                "id": st.column_config.TextColumn("ID", width="small"),
                "text1": st.column_config.TextColumn("Text 1", width="medium"),
                "text2": st.column_config.TextColumn("Text 2", width="medium"),
            },
            height=min(350, 45 * len(df) + 38),
        )

        # Lưu các text đã sửa vào overrides
        c1, c2 = st.columns([3, 1])
        with c1:
            if not edited.equals(df):
                st.info("✏️ Bạn đã sửa text. Nhấn 'Lưu thay đổi' để áp dụng.")
        with c2:
            if st.button("💾 Lưu thay đổi text", use_container_width=True):
                ov = st.session_state.setdefault("overrides", {})
                for _, row in edited.iterrows():
                    orig = df[df["id"] == row["id"]].iloc[0]
                    if row["text1"] != orig["text1"] or row["text2"] != orig["text2"]:
                        o = ov.setdefault(row["id"], {})
                        o["t1"] = row["text1"]
                        o["t2"] = row["text2"]
                st.session_state["df"] = edited.reset_index(drop=True)
                st.success("Đã lưu!")
                st.rerun()

    st.divider()
    st.markdown("### 🖼️ Bước 2 — Ảnh sản phẩm")
    st.caption("Tên file chứa **id** sản phẩm. VD: `SP001.png`, `sp001_main.jpg`")

    img_files = st.file_uploader(
        "Ảnh SP", type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True, label_visibility="collapsed",
    )
    if img_files:
        st.session_state["img_files"] = img_files

    imgs = st.session_state.get("img_files")
    if df is not None and imgs:
        mapping, orig_names, matched, unmatched = _match(df, imgs)
        st.session_state["mapping"] = mapping
        st.session_state["orig_names"] = orig_names

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📋 Excel", len(df))
        c2.metric("✅ Đã khớp", len(matched))
        c3.metric("❌ Thiếu ảnh", len(unmatched))
        c4.metric("🖼️ Ảnh upload", len(imgs))

        if unmatched:
            with st.expander(f"⚠️ {len(unmatched)} SP chưa có ảnh"):
                st.write(unmatched)


# ─────── TAB TEST NHANH ───────
with tab_single:
    st.markdown("### 🔬 Test 1 ảnh — xem preview tức thì")

    c_l, c_r = st.columns([1, 1], gap="large")
    with c_l:
        single_img = st.file_uploader(
            "Ảnh SP", type=["png","jpg","jpeg","webp"], key="single_up",
        )
        s_id = st.text_input("ID", "DEMO001")
        s_t1 = st.text_input("Text 1", "BLUETOOTH 5.4")
        s_t2 = st.text_input("Text 2", "CỔNG SẠC TYPE-C")

    with c_r:
        if single_img:
            try:
                prod = Image.open(single_img)
                bg = _bg()
                cfg = _build_config_for(None)
                thumb, info = build_thumbnail(prod, s_t1, s_t2, bg, cfg)
                st.image(thumb, use_container_width=True)
                sizes = info["font_sizes_used"]
                shrunk = " ⚡ shrunk" if info["any_shrunk"] else ""
                st.caption(f"600×600 · Font {sizes}{shrunk}")
                fmt_low = out_fmt.lower()
                data = pil_to_bytes(thumb, fmt_low, jpg_q)
                st.download_button(
                    f"⬇️ Tải {s_id}.{fmt_low}", data,
                    f"{sanitize_filename(s_id)}.{fmt_low}",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(str(e))
        else:
            with st.container(border=True):
                st.markdown(
                    "<div style='text-align:center;padding:60px 0;color:#94a3b8;'>"
                    "<div style='font-size:48px;'>🖼️</div>"
                    "<div style='font-size:14px;margin-top:8px;'>Upload ảnh bên trái để xem preview</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )


# ─────── TAB PREVIEW ───────
with tab_preview:
    df = _effective_df()
    mapping = st.session_state.get("mapping", {})

    if df.empty or not mapping:
        with st.container(border=True):
            st.markdown(
                "<div style='text-align:center;padding:60px 0;color:#94a3b8;'>"
                "<div style='font-size:48px;'>📋</div>"
                "<div style='font-size:14px;margin-top:8px;'>Hoàn tất tab Upload để xem preview</div>"
                "</div>",
                unsafe_allow_html=True,
            )
    else:
        c1, c2, c3 = st.columns([3, 1, 1])
        with c1:
            search = st.text_input("🔍 Tìm", placeholder="ID hoặc text...",
                                    label_visibility="collapsed")
        with c2:
            cols_n = st.selectbox("Cột", [2, 3, 4, 6], index=2, label_visibility="collapsed")
        with c3:
            max_n = st.selectbox("Số lượng", [12, 24, 48, 100], index=1, label_visibility="collapsed")

        dfv = df[df["id"].isin(mapping.keys())].copy()
        if search:
            s = search.lower()
            dfv = dfv[
                dfv["id"].str.lower().str.contains(s, na=False) |
                dfv["text1"].str.lower().str.contains(s, na=False) |
                dfv["text2"].str.lower().str.contains(s, na=False)
            ]

        if len(dfv) == 0:
            st.warning("Không tìm thấy.")
        else:
            ov_all = st.session_state.get("overrides", {})
            bg = _bg()
            rows = dfv.head(max_n).to_dict("records")
            prog = st.progress(0.0, text=f"Rendering {len(rows)}...")
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
                            override_dot = " 🎯" if pid in ov_all and any(
                                k for k in ov_all[pid] if k not in ("t1", "t2")
                            ) else ""
                            shrunk = " ⚡" if info["any_shrunk"] else ""
                            st.markdown(f"**{pid}**{override_dot}{shrunk}")
                            meta = row["text1"]
                            if row["text2"]: meta += f" · {row['text2']}"
                            st.caption(meta[:60] + ("…" if len(meta) > 60 else ""))
                except Exception as e:
                    with cols[i % cols_n]:
                        st.error(f"{pid}: {e}")

            prog.empty()
            if len(dfv) > max_n:
                st.info(f"Hiện {max_n}/{len(dfv)}. Tăng số lượng để xem thêm.")


# ─────── TAB CHỈNH TỪNG TẤM ───────
with tab_edit:
    df = _effective_df()
    mapping = st.session_state.get("mapping", {})

    if df.empty or not mapping:
        with st.container(border=True):
            st.markdown(
                "<div style='text-align:center;padding:60px 0;color:#94a3b8;'>"
                "<div style='font-size:48px;'>✏️</div>"
                "<div style='font-size:14px;margin-top:8px;'>Hoàn tất tab Upload trước</div>"
                "</div>",
                unsafe_allow_html=True,
            )
    else:
        st.markdown("### ✏️ Chỉnh từng sản phẩm riêng lẻ")
        st.caption("Mỗi SP có thể có cấu hình riêng, ghi đè lên cấu hình chung ở sidebar.")

        valid_ids = [pid for pid in df["id"].tolist() if pid in mapping]

        # Selector
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            pid = st.selectbox(
                "Chọn sản phẩm",
                valid_ids,
                format_func=lambda x: f"🎯 {x}" if x in st.session_state.get("overrides", {})
                                       and any(k for k in st.session_state["overrides"][x] if k not in ("t1","t2"))
                                       else x,
            )
        with c2:
            # Đi sang SP tiếp theo
            idx = valid_ids.index(pid) if pid in valid_ids else 0
            if st.button("◀ SP trước", use_container_width=True, disabled=idx == 0):
                st.session_state["_next_pid"] = valid_ids[idx - 1]
                st.rerun()
        with c3:
            if st.button("SP sau ▶", use_container_width=True, disabled=idx >= len(valid_ids) - 1):
                st.session_state["_next_pid"] = valid_ids[idx + 1]
                st.rerun()

        if "_next_pid" in st.session_state:
            pid = st.session_state.pop("_next_pid")

        row = df[df["id"] == pid].iloc[0]
        ov = st.session_state.get("overrides", {}).get(pid, {})

        c_left, c_right = st.columns([1.1, 1], gap="large")

        # LEFT: preview lớn
        with c_left:
            try:
                prod = Image.open(io.BytesIO(mapping[pid]))
                cfg = _build_config_for(pid)
                thumb, info = build_thumbnail(prod, row["text1"], row["text2"], _bg(), cfg)
                st.image(thumb, use_container_width=True)
                sizes = info["font_sizes_used"]
                shrunk = " ⚡ đã shrink" if info["any_shrunk"] else ""
                st.caption(f"600×600 · Font {sizes}{shrunk} · Ảnh gốc: {prod.size[0]}×{prod.size[1]}")
            except Exception as e:
                st.error(str(e))

        # RIGHT: controls
        with c_right:
            with st.container(border=True):
                st.markdown(f"### ⚙️ Cấu hình riêng: `{pid}`")

                use_override = st.toggle(
                    "Bật cấu hình riêng",
                    value=bool(ov) and any(k for k in ov if k not in ("t1","t2")),
                    key=f"use_ov_{pid}",
                )

                if use_override:
                    st.caption("Các giá trị sẽ ghi đè cấu hình chung.")

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
                        new_font = st.number_input("Font size", 9.0, 30.0, float(cur_font), 0.2,
                                                   format="%.1f", key=f"ov_font_{pid}")
                        new_center = st.radio("Căn", ["centroid","bbox"], index=0 if cur_center=="centroid" else 1,
                                              horizontal=True, key=f"ov_center_{pid}",
                                              format_func=lambda x: "Trọng tâm" if x == "centroid" else "Khung")

                    if st.button("💾 Lưu cấu hình riêng", type="primary", use_container_width=True):
                        st.session_state.setdefault("overrides", {}).setdefault(pid, {}).update({
                            "top_margin": new_top, "bottom_margin": new_bot,
                            "side_padding": new_side, "product_scale": new_scale,
                            "center_mode": new_center, "font_size": new_font,
                        })
                        st.success("Đã lưu!")
                        st.rerun()
                else:
                    # Nếu tắt override → xoá phần cfg (giữ t1/t2)
                    if ov and any(k for k in ov if k not in ("t1","t2")):
                        if st.button("🗑️ Xoá cấu hình riêng", use_container_width=True):
                            new_ov = {k: v for k, v in ov.items() if k in ("t1","t2")}
                            if new_ov:
                                st.session_state["overrides"][pid] = new_ov
                            else:
                                st.session_state["overrides"].pop(pid, None)
                            st.rerun()
                    else:
                        st.info("SP này đang dùng cấu hình chung. Bật toggle trên để tuỳ chỉnh riêng.")

                st.divider()
                st.markdown("**📝 Sửa text**")
                new_t1 = st.text_input("Text 1", value=row["text1"], key=f"t1_{pid}")
                new_t2 = st.text_input("Text 2", value=row["text2"], key=f"t2_{pid}")
                if new_t1 != row["text1"] or new_t2 != row["text2"]:
                    if st.button("💾 Lưu text", use_container_width=True, key=f"save_txt_{pid}"):
                        o = st.session_state.setdefault("overrides", {}).setdefault(pid, {})
                        o["t1"] = new_t1
                        o["t2"] = new_t2
                        # Cập nhật luôn df gốc để hiển thị đúng
                        base_df = st.session_state["df"]
                        base_df.loc[base_df["id"] == pid, "text1"] = new_t1
                        base_df.loc[base_df["id"] == pid, "text2"] = new_t2
                        st.success("Đã lưu!")
                        st.rerun()


# ─────── TAB XUẤT ZIP ───────
with tab_export:
    df = _effective_df()
    mapping = st.session_state.get("mapping", {})

    if df.empty or not mapping:
        with st.container(border=True):
            st.markdown(
                "<div style='text-align:center;padding:60px 0;color:#94a3b8;'>"
                "<div style='font-size:48px;'>📦</div>"
                "<div style='font-size:14px;margin-top:8px;'>Hoàn tất tab Upload trước</div>"
                "</div>",
                unsafe_allow_html=True,
            )
    else:
        n_total = len(mapping)
        n_ov = sum(
            1 for pid in mapping
            if any(k for k in st.session_state.get("overrides", {}).get(pid, {})
                   if k not in ("t1", "t2"))
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🖼️ Thumbnail", n_total)
        c2.metric("📐 Format", out_fmt)
        c3.metric("📏 Size", "600²")
        c4.metric("🎯 Tuỳ chỉnh", n_ov)

        st.markdown("")
        c1, c2 = st.columns([2, 1])
        with c1:
            include_csv = st.checkbox("📄 Kèm CMS (csv + xlsx)", True)
            include_src = st.checkbox("🗂️ Kèm ảnh gốc (`source/`)", False)
        with c2:
            zip_name = st.text_input("Tên ZIP", f"thumbnails_{time.strftime('%Y%m%d_%H%M')}.zip")

        st.markdown("")
        if st.button("🚀 Tạo & Tải ZIP", type="primary", use_container_width=True):
            bg = _bg()
            fmt_low = out_fmt.lower()
            prog = st.progress(0.0, text="Đang render...")
            zbuf = io.BytesIO()
            cms = []
            t0 = time.time()
            dfex = df[df["id"].isin(mapping.keys())].reset_index(drop=True)
            total = len(dfex)

            with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for i, row in dfex.iterrows():
                    pid = row["id"]
                    prog.progress((i + 1) / total, text=f"[{i+1}/{total}] {pid}")
                    try:
                        prod = Image.open(io.BytesIO(mapping[pid]))
                        cfg = _build_config_for(pid)
                        thumb, info = build_thumbnail(prod, row["text1"], row["text2"], bg, cfg)
                        sid = sanitize_filename(pid)
                        fname = f"{sid}.{fmt_low}"
                        zf.writestr(f"thumbnails/{fname}", pil_to_bytes(thumb, fmt_low, jpg_q))

                        if include_src:
                            orig_names = st.session_state.get("orig_names", {})
                            ext = Path(orig_names.get(pid, f"{pid}.png")).suffix or ".png"
                            zf.writestr(f"source/{sid}{ext}", mapping[pid])

                        has_ov = any(k for k in st.session_state.get("overrides", {}).get(pid, {})
                                    if k not in ("t1", "t2"))
                        cms.append({
                            "id": pid, "text1": row["text1"], "text2": row["text2"],
                            "filename": fname,
                            "fonts": ";".join(str(s) for s in info["font_sizes_used"]),
                            "shrunk": "yes" if info["any_shrunk"] else "no",
                            "custom_config": "yes" if has_ov else "no",
                        })
                    except Exception as e:
                        cms.append({
                            "id": pid, "text1": row["text1"], "text2": row["text2"],
                            "filename": "ERROR", "fonts": "", "shrunk": str(e),
                            "custom_config": "no",
                        })

                if include_csv and cms:
                    cdf = pd.DataFrame(cms)
                    zf.writestr("cms.csv",
                                cdf.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"))
                    xb = io.BytesIO()
                    with pd.ExcelWriter(xb, engine="openpyxl") as w:
                        cdf.to_excel(w, index=False, sheet_name="CMS")
                    zf.writestr("cms.xlsx", xb.getvalue())

            prog.empty()
            st.success(f"✅ Xong {total} thumbnail trong {time.time()-t0:.1f}s")
            st.download_button("⬇️ TẢI FILE ZIP", zbuf.getvalue(), zip_name,
                              "application/zip", use_container_width=True)
