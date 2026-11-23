import streamlit as st
from streamlit.navigation.page import StreamlitPage

from core.config import get_admin_emails
from domain.access import User
from services import users as users_service

USER_KEY = "current_user"
PAGES_KEY = "navigation_pages"


def resolve_current_user() -> User | None:
    if not st.user.get("is_logged_in", False):
        st.session_state.pop(USER_KEY, None)
        return None
    email = str(st.user.email).strip().lower()
    cached: User | None = st.session_state.get(USER_KEY)
    if cached is None or cached.email != email:
        name = str(st.user.get("name") or email)
        user = users_service.sign_in(email, name, get_admin_emails())
    else:
        user = users_service.get_active_user(email)
    st.session_state[USER_KEY] = user
    return user


def get_session_user() -> User:
    user: User | None = st.session_state.get(USER_KEY)
    if user is None:
        st.stop()
    return user


def sign_out() -> None:
    st.session_state.clear()
    st.logout()


def remember_pages(pages: list[StreamlitPage]) -> None:
    st.session_state[PAGES_KEY] = {page.url_path: page for page in pages}


def available_pages() -> dict[str, StreamlitPage]:
    return st.session_state.get(PAGES_KEY, {})
