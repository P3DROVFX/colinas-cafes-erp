import streamlit as st


def render_login_page() -> None:
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.title("☕ Colinas Cafés")
        st.subheader("Sistema de Gestão Integrada")
        st.write(
            "Produção, torrefação, estoque, vendas e financeiro da Colinas Cafés em um só lugar. "
            "Entre com sua conta Google para continuar."
        )
        st.button("Entrar com Google", type="primary", icon=":material/login:", on_click=st.login, args=("google",))
