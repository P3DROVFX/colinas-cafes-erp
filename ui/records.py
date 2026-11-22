from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import streamlit as st

from core.errors import AppError
from services.master_data import RecordInUseError
from ui.feedback import flash
from ui.formatting import style_numbers

Record = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ListFilters:
    search: str
    include_inactive: bool


@dataclass(frozen=True, slots=True)
class RecordList:
    key: str
    noun: str
    new_label: str
    search_placeholder: str
    empty_message: str
    can_write: bool
    load: Callable[[ListFilters], list[Record]]
    to_table: Callable[[list[Record]], pd.DataFrame]
    describe: Callable[[Record], str]
    open_form: Callable[[Record | None], None]
    delete: Callable[[int], None]
    set_active: Callable[[int, bool], None]
    decimal_places: dict[str, int] = field(default_factory=dict)
    column_config: dict[str, Any] = field(default_factory=dict)
    can_create: bool = True
    can_edit: Callable[[Record], bool] = lambda record: True


def _table_version_key(key: str) -> str:
    return f"{key}_table_version"


def reset_selection(key: str) -> None:
    version_key = _table_version_key(key)
    st.session_state[version_key] = st.session_state.get(version_key, 0) + 1


def finish_action(key: str, message: str) -> None:
    reset_selection(key)
    flash(message)
    st.rerun()


def run_and_finish(key: str, action: Callable[[], object], message: str) -> None:
    try:
        action()
    except AppError as error:
        st.error(str(error))
    else:
        finish_action(key, message)


def _render_filters(page: RecordList) -> ListFilters:
    search_column, toggle_column, action_column = st.columns([3, 1.2, 1.2], vertical_alignment="bottom")
    search = search_column.text_input(
        "Buscar", placeholder=page.search_placeholder, key=f"{page.key}_search", label_visibility="collapsed"
    )
    include_inactive = toggle_column.toggle("Mostrar inativos", key=f"{page.key}_include_inactive")
    if (
        page.can_write
        and page.can_create
        and action_column.button(
            page.new_label, type="primary", icon=":material/add:", key=f"{page.key}_new", width="stretch"
        )
    ):
        page.open_form(None)
    return ListFilters(search.strip(), include_inactive)


def _select_record(page: RecordList, records: list[Record]) -> Record | None:
    version = st.session_state.get(_table_version_key(page.key), 0)
    event = st.dataframe(
        style_numbers(page.to_table(records), page.decimal_places),
        hide_index=True,
        width="stretch",
        column_config=page.column_config,
        on_select="rerun" if page.can_write else "ignore",
        selection_mode="single-row",
        placeholder="—",
        key=f"{page.key}_table_{version}",
    )
    if not page.can_write:
        return None
    rows = event.selection.rows
    return records[rows[0]] if rows and rows[0] < len(records) else None


def _confirm_delete(page: RecordList, record: Record) -> None:
    label = page.describe(record)
    in_use_key = f"{page.key}_in_use_{record['id']}"
    if in_use_message := st.session_state.get(in_use_key):
        st.warning(in_use_message, icon=":material/warning:")
        if st.button(f"Inativar {page.noun}", type="primary", icon=":material/block:"):
            run_and_finish(page.key, lambda: page.set_active(record["id"], False), f"Cadastro inativado: {label}.")
        return
    st.markdown(f"Excluir **{label}**? A exclusão não pode ser desfeita.")
    if st.button(f"Excluir {page.noun}", type="primary", icon=":material/delete:"):
        try:
            page.delete(record["id"])
        except RecordInUseError as error:
            st.session_state[in_use_key] = str(error)
            st.rerun(scope="fragment")
        except AppError as error:
            st.error(str(error))
        else:
            finish_action(page.key, f"Cadastro excluído: {label}.")


def _confirm_deactivate(page: RecordList, record: Record) -> None:
    label = page.describe(record)
    st.markdown(
        f"Inativar **{label}**? O cadastro sai das novas operações, mas continua nos históricos e relatórios. "
        "Você pode reativá-lo quando quiser."
    )
    if st.button(f"Inativar {page.noun}", type="primary", icon=":material/block:"):
        run_and_finish(page.key, lambda: page.set_active(record["id"], False), f"Cadastro inativado: {label}.")


def _render_record_actions(page: RecordList, record: Record) -> None:
    label = page.describe(record)
    with st.container(border=True):
        st.markdown(f"**{label}**")
        if record.get("is_system"):
            st.caption("Cadastro do sistema: as integrações dependem dele, então não pode ser excluído nem inativado.")
        with st.container(horizontal=True):
            if page.can_edit(record) and st.button("Editar", icon=":material/edit:", key=f"{page.key}_edit"):
                page.open_form(record)
            if record.get("is_system"):
                return
            if record["is_active"]:
                if st.button("Inativar", icon=":material/block:", key=f"{page.key}_deactivate"):
                    st.dialog(f"Inativar {page.noun}")(_confirm_deactivate)(page, record)
            elif st.button("Reativar", icon=":material/restart_alt:", key=f"{page.key}_reactivate"):
                run_and_finish(page.key, lambda: page.set_active(record["id"], True), f"Cadastro reativado: {label}.")
            if st.button("Excluir", icon=":material/delete:", key=f"{page.key}_delete"):
                st.dialog(f"Excluir {page.noun}")(_confirm_delete)(page, record)


def render_record_list(page: RecordList) -> None:
    filters = _render_filters(page)
    try:
        records = page.load(filters)
    except AppError as error:
        st.error(str(error))
        return
    if not records:
        message = "Nenhum cadastro encontrado para esta busca." if filters.search else page.empty_message
        if not filters.include_inactive:
            message += " Para ver os inativos, ligue Mostrar inativos."
        st.info(message, icon=":material/info:")
        return
    selected = _select_record(page, records)
    if selected is not None:
        _render_record_actions(page, selected)
    elif page.can_write:
        st.caption("Selecione uma linha para editar, inativar ou excluir.")


def render_save_button(
    page_key: str,
    record: Record | None,
    create_label: str,
    create: Callable[[], object],
    update: Callable[[int], object],
    created_message: str,
    updated_message: str,
) -> None:
    label = "Salvar alterações" if record else create_label
    if st.button(label, type="primary", icon=":material/check:", key=f"{page_key}_save"):
        if record:
            run_and_finish(page_key, lambda: update(record["id"]), updated_message)
        else:
            run_and_finish(page_key, create, created_message)


def open_record_form(title: str, render_body: Callable[[], None]) -> None:
    st.dialog(title, width="large")(render_body)()
