import streamlit as st

from services.system import get_system_status
from ui.formatting import format_datetime
from ui.labels import ROLE_LABELS
from ui.session import get_session_user


def render_home_page() -> None:
    user = get_session_user()
    first_name = user.name.split()[0]
    st.title(f"Olá, {first_name}!")
    st.write("Bem-vindo ao sistema de gestão da **Colinas Cafés**.")

    status = get_system_status()
    columns = st.columns(3)
    columns[0].metric("Seu perfil", ROLE_LABELS[user.role])
    columns[1].metric("Versão do banco", status.schema_version or "—")
    columns[2].metric("Horário do servidor", format_datetime(status.database_time))
