import pandas as pd
import streamlit as st

from core.errors import AppError
from domain.access import Role
from services import users as users_service
from ui.formatting import format_datetime
from ui.labels import ROLE_LABELS
from ui.session import get_session_user


def _users_table(users: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Nome": [user["name"] for user in users],
            "E-mail": [user["email"] for user in users],
            "Perfil": [ROLE_LABELS[Role(user["role"])] for user in users],
            "Ativo": [user["is_active"] for user in users],
            "Último acesso": [format_datetime(user["last_login_at"]) for user in users],
        }
    )


def _render_access_form(users: list[dict]) -> None:
    actor = get_session_user()
    users_by_id = {user["id"]: user for user in users}
    user_id = st.selectbox(
        "Usuário",
        options=list(users_by_id),
        format_func=lambda key: f"{users_by_id[key]['name']} ({users_by_id[key]['email']})",
    )
    selected = users_by_id[user_id]
    with st.form(f"user_access_form_{user_id}"):
        roles = list(Role)
        role = st.selectbox(
            "Perfil",
            options=roles,
            index=roles.index(Role(selected["role"])),
            format_func=ROLE_LABELS.get,
        )
        is_active = st.checkbox("Acesso ativo", value=selected["is_active"])
        if st.form_submit_button("Salvar alterações", type="primary"):
            try:
                users_service.update_user_access(actor, user_id, role, is_active)
            except AppError as error:
                st.error(str(error))
            else:
                st.success("Acesso atualizado.")
                st.rerun()


def render_users_page() -> None:
    st.title("Usuários")
    st.caption("Quem entra pela primeira vez recebe o perfil Visitante. Ajuste o perfil conforme a função da pessoa.")
    try:
        users = users_service.list_users(get_session_user())
    except AppError as error:
        st.error(str(error))
        return
    st.dataframe(_users_table(users), hide_index=True, width="stretch")
    st.subheader("Alterar acesso")
    _render_access_form(users)
