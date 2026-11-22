import streamlit as st

from domain.access import User
from ui.labels import ROLE_LABELS
from ui.session import sign_out


def render_sidebar(user: User) -> None:
    with st.sidebar:
        st.markdown(f"**{user.name}**  \n{user.email}")
        st.caption(f"Perfil: {ROLE_LABELS[user.role]}")
        st.button("Sair", icon=":material/logout:", on_click=sign_out, width="stretch")


def render_access_denied(message: str) -> None:
    st.error(message, icon=":material/block:")
    st.button("Sair", icon=":material/logout:", on_click=sign_out)
