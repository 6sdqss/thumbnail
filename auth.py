"""
auth.py
=======
Xác thực đăng nhập bằng mật khẩu.

Ưu tiên đọc từ:
  1. st.secrets["APP_PASSWORD"]       (khi deploy Streamlit Cloud)
  2. os.environ["APP_PASSWORD"]        (khi chạy local qua biến môi trường)
  3. fallback: "admin123"              (chỉ dùng để demo - NÊN ĐỔI)

Mật khẩu KHÔNG hard-code trong app.py -> code public cũng không lộ.
"""
from __future__ import annotations

import hashlib
import os
import time
from typing import Optional

import streamlit as st


def _get_configured_password() -> str:
    """Lấy mật khẩu đã cấu hình từ secrets/env."""
    try:
        if "APP_PASSWORD" in st.secrets:
            return str(st.secrets["APP_PASSWORD"])
    except Exception:
        pass
    env = os.environ.get("APP_PASSWORD")
    if env:
        return env
    return "admin123"  # fallback demo - ĐỔI KHI DEPLOY


def _hash(pwd: str) -> str:
    return hashlib.sha256(pwd.encode("utf-8")).hexdigest()


def require_login() -> bool:
    """
    Render form đăng nhập.
    Return True nếu đã login, False nếu chưa.
    Gọi hàm này đầu app; nếu False thì st.stop().
    """
    if st.session_state.get("authenticated"):
        return True

    # Rate-limit đơn giản: sau 5 lần sai phải đợi 30s
    fail_count = st.session_state.get("login_fail_count", 0)
    last_fail = st.session_state.get("login_last_fail", 0)
    cooldown_left = 0
    if fail_count >= 5:
        cooldown_left = max(0, 30 - int(time.time() - last_fail))

    # UI login
    st.markdown(
        """
        <div style='text-align:center; padding:24px 0 8px;'>
          <div style='font-size:52px;'>🖼️</div>
          <h1 style='margin:0; font-weight:800; letter-spacing:-0.5px;'>Thumbnail Builder Pro</h1>
          <p style='color:#667; margin-top:6px;'>Tạo thumbnail sản phẩm 600×600 chuyên nghiệp</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _, col, _ = st.columns([1, 2, 1])
    with col:
        with st.container(border=True):
            st.markdown("#### 🔐 Đăng nhập")
            pwd = st.text_input(
                "Mật khẩu",
                type="password",
                placeholder="Nhập mật khẩu để sử dụng",
                disabled=cooldown_left > 0,
                label_visibility="collapsed",
            )

            if cooldown_left > 0:
                st.warning(f"⏳ Quá nhiều lần sai. Vui lòng đợi {cooldown_left}s.")
                return False

            if st.button("Đăng nhập", type="primary", use_container_width=True):
                configured = _get_configured_password()
                if _hash(pwd) == _hash(configured):
                    st.session_state["authenticated"] = True
                    st.session_state["login_fail_count"] = 0
                    st.rerun()
                else:
                    st.session_state["login_fail_count"] = fail_count + 1
                    st.session_state["login_last_fail"] = time.time()
                    st.error("❌ Mật khẩu không đúng")
                    return False

            st.caption(
                "💡 Mật khẩu được cấu hình qua `st.secrets` hoặc biến môi trường "
                "`APP_PASSWORD`. Mặc định demo: `admin123`."
            )
    return False


def logout_button(placement: Optional[object] = None) -> None:
    """Nút đăng xuất, có thể đặt trong sidebar."""
    target = placement or st
    if target.button("🚪 Đăng xuất", use_container_width=True):
        for k in ("authenticated", "login_fail_count", "login_last_fail"):
            st.session_state.pop(k, None)
        st.rerun()
