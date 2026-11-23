import pandas as pd
import streamlit as st

from core.errors import AppError
from services import integrity as integrity_service
from ui.session import get_session_user


def render_integrity_page() -> None:
    actor = get_session_user()
    st.title("Painel de integridade")
    st.caption("Cada verificação confere uma regra de consistência entre módulos. Todas devem ficar sem divergências.")
    st.button("Verificar de novo", icon=":material/refresh:")
    try:
        with st.spinner("Conferindo estoque e financeiro…"):
            results = integrity_service.run_integrity_checks(actor)
    except AppError as error:
        st.error(str(error))
        return
    passed = sum(result.passed for result in results)
    st.metric("Verificações sem divergência", f"{passed} de {len(results)}")
    for result in results:
        with st.container(border=True):
            if result.passed:
                st.markdown(f":green-badge[:material/check_circle: OK] **{result.code}** · {result.title}")
                continue
            badge = f":red-badge[:material/error: {len(result.divergences)} divergência(s)]"
            st.markdown(f"{badge} **{result.code}** · {result.title}")
            st.dataframe(pd.DataFrame(result.divergences), hide_index=True, width="stretch")
