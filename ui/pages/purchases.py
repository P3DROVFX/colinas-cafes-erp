from datetime import timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st

from core.clock import today
from core.errors import AppError
from domain.access import Permission, User, has_permission
from domain.finance import EntryDisplayStatus, split_installments
from domain.inventory import MovementType, StockItemKind
from domain.partners import SupplyType
from domain.purchasing import (
    MAX_INSTALLMENTS,
    PurchaseInput,
    PurchaseItemInput,
    PurchaseStatus,
    item_kind_for_supplier,
)
from services import partners as partners_service
from services import purchases as purchases_service
from services.purchases import PurchaseDetail, PurchaseFilters
from ui.effects import remember_effects, show_effects
from ui.feedback import show_flash
from ui.formatting import format_currency, style_numbers, to_float
from ui.forms import form_key, record_selectbox, to_decimal
from ui.labels import ENTRY_STATUS_BADGES, MOVEMENT_TYPE_LABELS, PURCHASE_STATUS_BADGES
from ui.records import finish_action, run_and_finish
from ui.session import get_session_user

PAGE_KEY = "purchases"
ITEM_COLUMN = "Item"
QUANTITY_COLUMN = "Quantidade"
COST_COLUMN = "Custo unitário (R$)"
DATE_COLUMN = st.column_config.DateColumn(format="DD/MM/YYYY")


def _purchase_suppliers(actor: User, include_id: int | None = None) -> list[dict[str, Any]]:
    return [
        supplier
        for supply_type in (SupplyType.GREEN_COFFEE, SupplyType.PACKAGING)
        for supplier in partners_service.list_supplier_options(actor, supply_type, include_id)
    ]


def _status_badge(status: PurchaseStatus) -> None:
    label, color, icon = PURCHASE_STATUS_BADGES[status]
    st.badge(label, color=color, icon=icon)


def _render_filters(actor: User) -> PurchaseFilters:
    period_column, supplier_column, status_column, action_column = st.columns(
        [1.4, 1.4, 1.6, 1], vertical_alignment="bottom"
    )
    period = period_column.date_input(
        "Período do pedido",
        value=(today() - timedelta(days=90), today()),
        format="DD/MM/YYYY",
        key=f"{PAGE_KEY}_period",
    )
    supplier_id = record_selectbox(
        supplier_column,
        "Fornecedor",
        _purchase_suppliers(actor),
        None,
        f"{PAGE_KEY}_supplier_filter",
        lambda supplier: supplier["name"],
        placeholder="Todos",
    )
    statuses = status_column.multiselect(
        "Situação",
        list(PurchaseStatus),
        default=[PurchaseStatus.PENDING, PurchaseStatus.RECEIVED],
        format_func=lambda status: PURCHASE_STATUS_BADGES[status][0],
        key=f"{PAGE_KEY}_statuses",
    )
    if has_permission(actor, Permission.MANAGE_PURCHASES) and action_column.button(
        "Nova compra", type="primary", icon=":material/add:", width="stretch"
    ):
        st.dialog("Nova compra", width="large")(_render_purchase_form)(actor, None)
    start, end = period if len(period) == 2 else (period[0], period[0])
    return PurchaseFilters(start, end, supplier_id, tuple(statuses or PurchaseStatus))


def _purchases_table(purchases: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Número": [row["number"] for row in purchases],
            "Fornecedor": [row["supplier_name"] for row in purchases],
            "Pedido": [row["order_date"] for row in purchases],
            "Previsão": [row["expected_date"] for row in purchases],
            "Recebida em": [row["received_date"] for row in purchases],
            "Total (R$)": [to_float(row["total_amount"]) for row in purchases],
            "Parcelas": [row["installments"] for row in purchases],
            "Situação": [PURCHASE_STATUS_BADGES[PurchaseStatus(row["status"])][0] for row in purchases],
        }
    )


def _item_rows(detail: PurchaseDetail | None, labels_by_id: dict[int, str]) -> pd.DataFrame:
    items = detail.items if detail else []
    return pd.DataFrame(
        {
            ITEM_COLUMN: pd.Series([labels_by_id.get(item["item_id"]) for item in items], dtype="object"),
            QUANTITY_COLUMN: pd.Series([to_float(item["quantity"]) for item in items], dtype="float"),
            COST_COLUMN: pd.Series([to_float(item["unit_cost"]) for item in items], dtype="float"),
        }
    )


def _parse_items(rows: pd.DataFrame, ids_by_label: dict[str, int], kind: StockItemKind) -> tuple:
    items = []
    for row in rows.to_dict("records"):
        label = row[ITEM_COLUMN]
        if not isinstance(label, str) or label not in ids_by_label:
            continue
        quantity = to_decimal(row[QUANTITY_COLUMN], 3) if pd.notna(row[QUANTITY_COLUMN]) else Decimal("0")
        unit_cost = to_decimal(row[COST_COLUMN], 4) if pd.notna(row[COST_COLUMN]) else Decimal("0")
        items.append(PurchaseItemInput(kind, ids_by_label[label], quantity, unit_cost))
    return tuple(items)


def _render_items_editor(actor: User, supplier: dict[str, Any], detail: PurchaseDetail | None, key: str) -> tuple:
    kind = item_kind_for_supplier(SupplyType(supplier["supply_type"]))
    options = purchases_service.list_purchasable_items(actor, supplier["id"])
    ids_by_label = {option["label"]: option["id"] for option in options}
    unit = "kg" if kind is StockItemKind.GREEN_COFFEE else "un."
    if not options:
        st.warning("Este fornecedor ainda não tem itens à venda. Cadastre o café da fazenda parceira ou a embalagem.")
    edited = st.data_editor(
        _item_rows(
            detail if detail and detail.purchase["supplier_id"] == supplier["id"] else None,
            {item_id: label for label, item_id in ids_by_label.items()},
        ),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key=f"{key}_items_{supplier['id']}",
        column_config={
            ITEM_COLUMN: st.column_config.SelectboxColumn(options=list(ids_by_label), required=True, width="large"),
            QUANTITY_COLUMN: st.column_config.NumberColumn(
                f"Quantidade ({unit})", min_value=0.0, step=0.001 if unit == "kg" else 1.0, required=True
            ),
            COST_COLUMN: st.column_config.NumberColumn(min_value=0.0, step=0.01, format="%.2f", required=True),
        },
    )
    return _parse_items(edited, ids_by_label, kind)


def _render_purchase_form(actor: User, detail: PurchaseDetail | None) -> None:
    purchase = detail.purchase if detail else {}
    key = form_key(PAGE_KEY, purchase or None)
    suppliers = _purchase_suppliers(actor, purchase.get("supplier_id"))
    suppliers_by_id = {supplier["id"]: supplier for supplier in suppliers}
    supplier_id = record_selectbox(
        st,
        "Fornecedor",
        suppliers,
        purchase.get("supplier_id"),
        f"{key}_supplier",
        lambda supplier: supplier["name"],
    )
    if supplier_id is None:
        st.info("Escolha o fornecedor para listar os itens que ele vende.", icon=":material/info:")
        return
    supplier = suppliers_by_id[supplier_id]
    items = _render_items_editor(actor, supplier, detail, key)
    order_date = purchase.get("order_date", today())
    left, middle, right = st.columns(3)
    freight = left.number_input(
        "Frete (R$)", min_value=0.0, step=10.0, format="%.2f",
        value=to_float(purchase.get("freight_amount")) or 0.0, key=f"{key}_freight",
    )  # fmt: skip
    installments = middle.number_input(
        "Parcelas", min_value=1, max_value=MAX_INSTALLMENTS, step=1,
        value=purchase.get("installments", 1), key=f"{key}_installments",
    )  # fmt: skip
    first_due_days = right.number_input(
        "Dias até a 1ª parcela", min_value=0, max_value=365, step=1,
        value=purchase.get("first_due_days", 30), key=f"{key}_first_due",
        help="As demais parcelas vencem a cada 30 dias.",
    )  # fmt: skip
    left, middle, right = st.columns(3)
    expected_date = left.date_input(
        "Previsão de entrega",
        value=purchase.get("expected_date") or order_date + timedelta(days=supplier["lead_time_days"]),
        min_value=order_date,
        format="DD/MM/YYYY",
        key=f"{key}_expected_{supplier_id}",
        help=f"Sugerida pelo prazo médio do fornecedor ({supplier['lead_time_days']} dias).",
    )
    supplier_invoice = middle.text_input(
        "NF do fornecedor", value=purchase.get("supplier_invoice") or "", key=f"{key}_invoice"
    )
    requested_date = None
    if not detail and has_permission(actor, Permission.BACKDATE_OPERATIONS):
        requested_date = right.date_input(
            "Data do pedido", value=today(), max_value=today(), format="DD/MM/YYYY", key=f"{key}_order_date",
            help="Só o administrador registra pedidos com data retroativa.",
        )  # fmt: skip
    notes = st.text_area("Observação", value=purchase.get("notes") or "", key=f"{key}_notes", height=68)
    data = PurchaseInput(
        supplier_id=supplier_id,
        items=items,
        freight_amount=to_decimal(freight),
        installments=int(installments),
        first_due_days=int(first_due_days),
        expected_date=expected_date,
        supplier_invoice=supplier_invoice,
        notes=notes,
    )
    total = sum((item.quantity * item.unit_cost for item in items), Decimal("0")) + data.freight_amount
    st.markdown(f"Total do pedido: **{format_currency(total)}** em {data.installments}x")
    if detail:
        if st.button("Salvar alterações", type="primary", icon=":material/check:"):
            run_and_finish(
                PAGE_KEY,
                lambda: purchases_service.update_purchase(actor, purchase["id"], data),
                f"Compra {purchase['number']} atualizada.",
            )
    elif st.button("Criar pedido", type="primary", icon=":material/check:"):
        try:
            number = purchases_service.create_purchase(actor, data, requested_date)
        except AppError as error:
            st.error(str(error))
        else:
            finish_action(PAGE_KEY, f"Pedido {number} criado.")


def _render_receive_dialog(actor: User, detail: PurchaseDetail) -> None:
    purchase = detail.purchase
    st.markdown(
        f"Receber **{purchase['number']}** de {purchase['supplier_name']}? Os itens entram no estoque com o frete "
        "rateado no custo, e as parcelas viram títulos a pagar."
    )
    received_date = None
    if has_permission(actor, Permission.BACKDATE_OPERATIONS):
        received_date = st.date_input(
            "Data do recebimento", value=today(), min_value=purchase["order_date"], max_value=today(),
            format="DD/MM/YYYY",
        )  # fmt: skip
    installments = split_installments(
        purchase["total_amount"], purchase["installments"], received_date or today(), purchase["first_due_days"]
    )
    for installment in installments:
        st.markdown(
            f"- Parcela {installment.number}/{installment.count}: {format_currency(installment.amount)}, "
            f"vence {installment.due_date:%d/%m/%Y}"
        )
    if st.button("Receber compra", type="primary", icon=":material/inventory:"):
        try:
            effects = purchases_service.receive_purchase(actor, purchase["id"], received_date)
        except AppError as error:
            st.error(str(error))
        else:
            remember_effects(f"Compra {purchase['number']} recebida.", effects)
            finish_action(PAGE_KEY, f"Compra {purchase['number']} recebida.")


def _render_cancel_dialog(actor: User, detail: PurchaseDetail) -> None:
    purchase = detail.purchase
    st.markdown(f"Cancelar o pedido **{purchase['number']}**? Ele não gerou estoque nem títulos.")
    reason = st.text_input("Motivo do cancelamento")
    if st.button("Cancelar pedido", type="primary", icon=":material/block:"):
        run_and_finish(
            PAGE_KEY,
            lambda: purchases_service.cancel_purchase(actor, purchase["id"], reason),
            f"Pedido {purchase['number']} cancelado.",
        )


def _render_reverse_dialog(actor: User, detail: PurchaseDetail) -> None:
    purchase = detail.purchase
    st.markdown(
        f"Estornar o recebimento de **{purchase['number']}**? Os itens saem do estoque, o custo médio volta ao "
        "valor anterior e as parcelas em aberto são canceladas. Só é possível se os itens ainda estiverem no "
        "estoque e nenhuma parcela tiver sido paga."
    )
    reason = st.text_input("Motivo do estorno")
    if st.button("Estornar recebimento", type="primary", icon=":material/undo:"):
        try:
            effects = purchases_service.reverse_purchase(actor, purchase["id"], reason)
        except AppError as error:
            st.error(str(error))
        else:
            remember_effects(f"Recebimento da compra {purchase['number']} estornado.", effects)
            finish_action(PAGE_KEY, f"Compra {purchase['number']} estornada.")


def _render_actions(actor: User, detail: PurchaseDetail) -> None:
    status = PurchaseStatus(detail.purchase["status"])
    with st.container(horizontal=True):
        if status is PurchaseStatus.PENDING:
            if has_permission(actor, Permission.RECEIVE_PURCHASES) and st.button(
                "Receber", icon=":material/inventory:"
            ):
                st.dialog("Receber compra")(_render_receive_dialog)(actor, detail)
            if has_permission(actor, Permission.MANAGE_PURCHASES) and st.button("Editar", icon=":material/edit:"):
                st.dialog("Editar compra", width="large")(_render_purchase_form)(actor, detail)
            if has_permission(actor, Permission.CANCEL_PURCHASES) and st.button("Cancelar", icon=":material/block:"):
                st.dialog("Cancelar pedido")(_render_cancel_dialog)(actor, detail)
        can_reverse = status is PurchaseStatus.RECEIVED and has_permission(actor, Permission.CANCEL_PURCHASES)
        if can_reverse and st.button("Estornar recebimento", icon=":material/undo:"):
            st.dialog("Estornar recebimento")(_render_reverse_dialog)(actor, detail)


def _render_items_tab(detail: PurchaseDetail) -> None:
    frame = pd.DataFrame(
        {
            "Item": [item["item_label"] for item in detail.items],
            "Quantidade": [to_float(item["quantity"]) for item in detail.items],
            "Custo unitário (R$)": [to_float(item["unit_cost"]) for item in detail.items],
            "Frete rateado (R$)": [to_float(item["allocated_freight"]) for item in detail.items],
            "Custo efetivo (R$)": [to_float(item["effective_unit_cost"]) for item in detail.items],
        }
    )
    places = {"Quantidade": 3, "Custo unitário (R$)": 2, "Frete rateado (R$)": 2, "Custo efetivo (R$)": 4}
    st.dataframe(style_numbers(frame, places), hide_index=True, width="stretch", placeholder="—")


def _render_entries_tab(detail: PurchaseDetail) -> None:
    if not detail.entries:
        st.caption("Os títulos a pagar são gerados no recebimento.")
        return
    frame = pd.DataFrame(
        {
            "Parcela": [f"{row['installment']}/{row['installment_count']}" for row in detail.entries],
            "Vencimento": [row["due_date"] for row in detail.entries],
            "Valor (R$)": [to_float(row["amount"]) for row in detail.entries],
            "Situação": [ENTRY_STATUS_BADGES[EntryDisplayStatus(row["display_status"])][0] for row in detail.entries],
        }
    )
    st.dataframe(
        style_numbers(frame, {"Valor (R$)": 2}),
        hide_index=True,
        width="stretch",
        column_config={"Vencimento": DATE_COLUMN},
    )


def _render_movements_tab(detail: PurchaseDetail) -> None:
    if not detail.movements:
        st.caption("Os movimentos de estoque são gerados no recebimento.")
        return
    frame = pd.DataFrame(
        {
            "Data": [row["movement_date"] for row in detail.movements],
            "Tipo": [MOVEMENT_TYPE_LABELS[MovementType(row["movement_type"])] for row in detail.movements],
            "Item": [row["item_label"] for row in detail.movements],
            "Quantidade": [to_float(row["quantity"]) for row in detail.movements],
            "Saldo após": [to_float(row["balance_after"]) for row in detail.movements],
            "Custo unitário (R$)": [to_float(row["unit_cost"]) for row in detail.movements],
            "Valor (R$)": [to_float(row["total_value"]) for row in detail.movements],
        }
    )
    places = {"Quantidade": 3, "Saldo após": 3, "Custo unitário (R$)": 4, "Valor (R$)": 2}
    st.dataframe(style_numbers(frame, places), hide_index=True, width="stretch", column_config={"Data": DATE_COLUMN})


def _render_detail(actor: User, purchase_id: int) -> None:
    try:
        detail = purchases_service.get_purchase_detail(actor, purchase_id)
    except AppError as error:
        st.error(str(error))
        return
    purchase = detail.purchase
    with st.container(border=True):
        title_column, badge_column = st.columns([4, 1], vertical_alignment="center")
        title_column.subheader(purchase["number"])
        with badge_column:
            _status_badge(PurchaseStatus(purchase["status"]))
        supplier_column, order_column, received_column, total_column = st.columns(4)
        supplier_column.markdown(f"**Fornecedor**  \n{purchase['supplier_name']}")
        order_column.markdown(f"**Pedido**  \n{purchase['order_date']:%d/%m/%Y}")
        received = purchase["received_date"] or purchase["expected_date"]
        received_label = "Recebida em" if purchase["received_date"] else "Previsão"
        received_column.markdown(f"**{received_label}**  \n{received:%d/%m/%Y}" if received else "**Previsão**  \n—")
        total_column.markdown(
            f"**Total**  \n{format_currency(purchase['total_amount'])} "
            f"(frete {format_currency(purchase['freight_amount'])})"
        )
        if purchase["cancel_reason"]:
            st.caption(f"Motivo: {purchase['cancel_reason']}")
        _render_actions(actor, detail)
        items_tab, entries_tab, movements_tab = st.tabs(["Itens", "Títulos a pagar", "Movimentos de estoque"])
        with items_tab:
            _render_items_tab(detail)
        with entries_tab:
            _render_entries_tab(detail)
        with movements_tab:
            _render_movements_tab(detail)


def render_purchases_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Compras")
    st.caption("Pedidos de café verde e de embalagens. O recebimento gera a entrada no estoque e as contas a pagar.")
    show_effects()
    filters = _render_filters(actor)
    try:
        purchases = purchases_service.list_purchases(actor, filters)
    except AppError as error:
        st.error(str(error))
        return
    if not purchases:
        st.info("Nenhuma compra no período e nas situações escolhidas.", icon=":material/info:")
        return
    version = st.session_state.get(f"{PAGE_KEY}_table_version", 0)
    event = st.dataframe(
        style_numbers(_purchases_table(purchases), {"Total (R$)": 2}),
        hide_index=True,
        width="stretch",
        placeholder="—",
        on_select="rerun",
        selection_mode="single-row",
        column_config={"Pedido": DATE_COLUMN, "Previsão": DATE_COLUMN, "Recebida em": DATE_COLUMN},
        key=f"{PAGE_KEY}_table_{version}",
    )
    rows = event.selection.rows
    if rows and rows[0] < len(purchases):
        _render_detail(actor, purchases[rows[0]]["id"])
    else:
        st.caption("Selecione uma compra para ver os itens, os títulos e as ações.")
