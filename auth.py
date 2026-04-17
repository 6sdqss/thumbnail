"""
auth.py — Xác thực đăng nhập
"""
from __future__ import annotations
import hashlib, hmac, os, time
from typing import Optional, Tuple
import streamlit as st

_DEFAULT_USERNAME = "ducpro"
_DEFAULT_PASSWORD = "234766"

def _get_credentials() -> Tuple[str, str]:
    user, pwd = _DEFAULT_USERNAME, _DEFAULT_PASSWORD
    try:
        if "APP_USERNAME" in st.secrets: user = str(st.secrets["APP_USERNAME"])
        if "APP_PASSWORD" in st.secrets: pwd = str(st.secrets["APP_PASSWORD"])
    except Exception: pass
    user = os.environ.get("APP_USERNAME", user)
    pwd = os.environ.get("APP_PASSWORD", pwd)
    return user, pwd

def _hash(s: str) -> str: return hashlib.sha256(s.encode()).hexdigest()
def _eq(a: str, b: str) -> bool: return hmac.compare_digest(_hash(a), _hash(b))

def require_login() -> bool:
    if st.session_state.get("authenticated"): return True
    fails = st.session_state.get("_f", 0)
    last = st.session_state.get("_lt", 0)
    cd = max(0, 30 - int(time.time() - last)) if fails >= 5 else 0

    st.markdown("""
    <style>
      .login-wrap{display:flex;align-items:center;justify-content:center;min-height:80vh;}
      .login-card{background:#fff;border-radius:20px;padding:48px 40px 36px;
        width:380px;max-width:92vw;box-shadow:0 8px 40px rgba(79,70,229,.12),0 1px 3px rgba(0,0,0,.06);
        text-align:center;position:relative;overflow:hidden;}
      .login-card::before{content:'';position:absolute;top:0;left:0;right:0;height:4px;
        background:linear-gradient(90deg,#4f46e5,#7c3aed,#ec4899);}
      .login-icon{font-size:48px;margin-bottom:12px;}
      .login-title{font-size:22px;font-weight:800;color:#1e1b4b;margin:0 0 4px;}
      .login-sub{font-size:13px;color:#6b7280;margin:0 0 28px;}
    </style>
    """, unsafe_allow_html=True)

    st.markdown("<div class='login-wrap'>", unsafe_allow_html=True)
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown("""
        <div class='login-card'>
          <div class='login-icon'>🖼️</div>
          <div class='login-title'>Thumbnail Builder Pro</div>
          <div class='login-sub'>Đăng nhập để sử dụng công cụ</div>
        </div>
        """, unsafe_allow_html=True)

        username = st.text_input("👤 Tên đăng nhập", placeholder="username", disabled=cd > 0, label_visibility="collapsed")
        password = st.text_input("🔒 Mật khẩu", type="password", placeholder="password", disabled=cd > 0, label_visibility="collapsed")

        if cd > 0:
            st.warning(f"Quá nhiều lần sai. Đợi {cd}s.")
            return False

        if st.button("Đăng nhập", type="primary", use_container_width=True):
            u, p = _get_credentials()
            if _eq(username.strip(), u) and _eq(password, p):
                st.session_state["authenticated"] = True
                st.session_state["login_user"] = u
                st.session_state["_f"] = 0
                st.rerun()
            else:
                st.session_state["_f"] = fails + 1
                st.session_state["_lt"] = time.time()
                st.error(f"Sai tên hoặc mật khẩu. Còn {max(0,5-fails-1)} lần thử.")
                return False
    st.markdown("</div>", unsafe_allow_html=True)
    return False

def logout_button(placement=None):
    t = placement or st
    user = st.session_state.get("login_user", "")
    if user: t.caption(f"👤 {user}")
    if t.button("Đăng xuất", use_container_width=True):
        for k in ("authenticated","login_user","_f","_lt"): st.session_state.pop(k, None)
        st.rerun()
