import streamlit as st
from streamlit.navigation.page import StreamlitPage

from domain.access import Permission, User, has_permission
from ui.pages.home import render_home_page
from ui.pages.users import render_users_page


def build_navigation(user: User) -> StreamlitPage:
    sections: dict[str, list[StreamlitPage]] = {
        "Geral": [
            st.Page(render_home_page, title="Início", icon=":material/home:", url_path="inicio", default=True),
        ],
    }
    if has_permission(user, Permission.MANAGE_USERS):
        sections["Administração"] = [
            st.Page(render_users_page, title="Usuários", icon=":material/group:", url_path="usuarios"),
        ]
    return st.navigation(sections)
