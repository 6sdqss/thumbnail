"""auth.py — Login 100% Streamlit native."""
import hashlib, hmac, os, time
from typing import Tuple
import streamlit as st

_U, _P = "ducpro", "234766"

def _creds() -> Tuple[str, str]:
    u, p = _U, _P
    try:
        u = st.secrets.get("APP_USERNAME", u)
        p = st.secrets.get("APP_PASSWORD", p)
    except: pass
    return os.environ.get("APP_USERNAME", u), os.environ.get("APP_PASSWORD", p)

def _h(s): return hashlib.sha256(s.encode()).hexdigest()

def require_login() -> bool:
    if st.session_state.get("ok"):
        return True

    fails = st.session_state.get("_fc", 0)
    cd = max(0, 30 - int(time.time() - st.session_state.get("_ft", 0))) if fails >= 5 else 0

    # Spacing + centered column
    for _ in range(3): st.write("")
    _, mid, _ = st.columns([1.3, 2, 1.3])
    with mid:
        with st.container(border=True):
            st.markdown("<h2 style='text-align:center;margin:0;'>🖼️</h2>", unsafe_allow_html=True)
            st.markdown("<h3 style='text-align:center;margin:0 0 2px;'>Thumbnail Builder Pro</h3>", unsafe_allow_html=True)
            st.caption("<p style='text-align:center;'>Nhập thông tin để đăng nhập</p>", unsafe_allow_html=True)

            username = st.text_input("Tên đăng nhập", disabled=cd > 0)
            password = st.text_input("Mật khẩu", type="password", disabled=cd > 0)

            if cd > 0:
                st.warning(f"Đợi {cd}s rồi thử lại")
                return False

            if st.button("🔐 Đăng nhập", type="primary", use_container_width=True):
                cu, cp = _creds()
                if hmac.compare_digest(_h(username.strip()), _h(cu)) and hmac.compare_digest(_h(password), _h(cp)):
                    st.session_state.update({"ok": True, "user": cu, "_fc": 0})
                    st.rerun()
                else:
                    st.session_state["_fc"] = fails + 1
                    st.session_state["_ft"] = time.time()
                    st.error(f"Sai thông tin ({max(0, 4 - fails)} lần thử còn)")
    return False

def logout_btn():
    u = st.session_state.get("user", "")
    if u: st.caption(f"👤 {u}")
    if st.button("Đăng xuất", use_container_width=True):
        for k in ("ok","user","_fc","_ft"): st.session_state.pop(k, None)
        st.rerun()
