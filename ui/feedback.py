import streamlit as st

FLASH_KEY = "flash_message"


def flash(message: str) -> None:
    st.session_state[FLASH_KEY] = message


def show_flash() -> None:
    if message := st.session_state.pop(FLASH_KEY, None):
        st.toast(message, icon=":material/check_circle:")
