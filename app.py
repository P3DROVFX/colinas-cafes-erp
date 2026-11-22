import streamlit as st

from core.errors import AccessDeniedError
from ui.layout import render_access_denied, render_sidebar
from ui.login import render_login_page
from ui.navigation import build_navigation
from ui.session import resolve_current_user

st.set_page_config(page_title="Colinas Cafés", page_icon="☕", layout="wide")


def main() -> None:
    try:
        user = resolve_current_user()
    except AccessDeniedError as error:
        render_access_denied(str(error))
        return
    if user is None:
        render_login_page()
        return
    render_sidebar(user)
    build_navigation(user).run()


main()
