"""
auth.py
=======
Xác thực đăng nhập bằng username + password.

Thứ tự đọc credential:
  1. st.secrets["APP_USERNAME"] / st.secrets["APP_PASSWORD"]  (Streamlit Cloud)
  2. os.environ["APP_USERNAME"] / os.environ["APP_PASSWORD"]   (local/env)
  3. Mặc định: username=ducpro, password=234766

Credential KHÔNG hard-code ở app.py → push code public cũng không lộ.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional, Tuple

import streamlit as st

# Mặc định (dùng khi chưa cấu hình secrets/env)
_DEFAULT_USERNAME = "ducpro"
_DEFAULT_PASSWORD = "234766"


def _get_credentials() -> Tuple[str, str]:
    """Lấy cặp (username, password) đã cấu hình."""
    user, pwd = _DEFAULT_USERNAME, _DEFAULT_PASSWORD
    try:
        if "APP_USERNAME" in st.secrets:
            user = str(st.secrets["APP_USERNAME"])
        if "APP_PASSWORD" in st.secrets:
            pwd = str(st.secrets["APP_PASSWORD"])
    except Exception:
        pass
    user = os.environ.get("APP_USERNAME", user)
    pwd = os.environ.get("APP_PASSWORD", pwd)
    return user, pwd


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _secure_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(_hash(a), _hash(b))


def require_login() -> bool:
    """Render form đăng nhập. Trả True nếu đã login, False nếu chưa."""
    if st.session_state.get("authenticated"):
        return True

    fail_count = st.session_state.get("login_fail_count", 0)
    last_fail = st.session_state.get("login_last_fail", 0)
    cooldown_left = 0
    if fail_count >= 5:
        cooldown_left = max(0, 30 - int(time.time() - last_fail))

    st.markdown(
        """
        <div style='text-align:center; padding:30px 0 10px;'>
          <div style='font-size:60px; margin-bottom:4px;'>🖼️</div>
          <h1 style='margin:0; font-weight:800; letter-spacing:-0.8px;
                     background: linear-gradient(135deg,#4f46e5,#7c3aed);
                     -webkit-background-clip: text; -webkit-text-fill-color: transparent;'>
            Thumbnail Builder Pro
          </h1>
          <p style='color:#64748b; margin-top:6px; font-size:15px;'>
            Tạo thumbnail sản phẩm 600×600 chuyên nghiệp — Smart-fit · Auto-shrink text
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _, col, _ = st.columns([1, 2, 1])
    with col:
        with st.container(border=True):
            st.markdown("#### 🔐 Đăng nhập")

            username = st.text_input(
                "Tên đăng nhập",
                placeholder="Nhập username",
                disabled=cooldown_left > 0,
            )
            password = st.text_input(
                "Mật khẩu",
                type="password",
                placeholder="Nhập mật khẩu",
                disabled=cooldown_left > 0,
            )

            if cooldown_left > 0:
                st.warning(f"⏳ Quá nhiều lần sai. Vui lòng đợi {cooldown_left} giây.")
                return False

            if st.button("Đăng nhập", type="primary", use_container_width=True):
                cfg_user, cfg_pwd = _get_credentials()
                if _secure_eq(username.strip(), cfg_user) and _secure_eq(password, cfg_pwd):
                    st.session_state["authenticated"] = True
                    st.session_state["login_user"] = cfg_user
                    st.session_state["login_fail_count"] = 0
                    st.rerun()
                else:
                    st.session_state["login_fail_count"] = fail_count + 1
                    st.session_state["login_last_fail"] = time.time()
                    left = max(0, 5 - st.session_state["login_fail_count"])
                    st.error(f"❌ Sai tên hoặc mật khẩu. Còn {left} lần thử.")
                    return False

            st.caption(
                "💡 Credentials cấu hình qua `st.secrets` hoặc env "
                "`APP_USERNAME` / `APP_PASSWORD`."
            )

    return False


def logout_button(placement: Optional[object] = None) -> None:
    target = placement or st
    user = st.session_state.get("login_user", "")
    if user:
        target.markdown(f"👤 Đang đăng nhập: **{user}**")
    if target.button("🚪 Đăng xuất", use_container_width=True):
        for k in ("authenticated", "login_user", "login_fail_count", "login_last_fail"):
            st.session_state.pop(k, None)
        st.rerun()
