from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st

from core.clock import today
from core.errors import AppError
from domain.access import Permission, User, has_permission
from domain.finance import EntryDisplayStatus
from domain.inventory import MovementType
from domain.numbers import format_decimal, round_money
from domain.sales import (
    CHANNEL_RULES,
    LATE_SHIPPING_DAYS,
    Channel,
    DeliveryType,
    PaymentMethod,
    SaleDisplayStatus,
    SaleInput,
    SaleItemInput,
    SaleProduct,
    SaleStatus,
    ShipmentInput,
    box_count,
    discount_pct,
    gross_margin_pct,
    is_late_shipment,
    needs_discount_approval,
    payment_fee,
    price_items,
    receivable_terms,
    sale_totals,
)
from services import sales as sales_service
from services.sales import SaleDetail, SaleFilters, SaleFormContext, SaleResult
from ui.documents import sale_document_pdf
from ui.effects import remember_effects, show_effects
from ui.feedback import show_flash
from ui.filters import period_input
from ui.formatting import format_currency, format_datetime, style_numbers, to_float
from ui.forms import record_selectbox, to_decimal
from ui.labels import (
    CHANNEL_LABELS,
    DELIVERY_TYPE_LABELS,
    ENTRY_STATUS_BADGES,
    MOVEMENT_TYPE_LABELS,
    PAYMENT_METHOD_LABELS,
    SALE_STATUS_BADGES,
)
from ui.records import finish_action
from ui.session import get_session_user

PAGE_KEY = "sales"
PRODUCT_COLUMN = "Produto"
QUANTITY_COLUMN = "Quantidade"
DATE_COLUMN = st.column_config.DateColumn(format="DD/MM/YYYY")
INVOICED = (SaleDisplayStatus.CONFIRMED, SaleDisplayStatus.SHIPPED, SaleDisplayStatus.DELIVERED)
DEFAULT_STATUSES = [status for status in SaleDisplayStatus if status is not SaleDisplayStatus.CANCELLED]
STATUS_LABELS = {status: badge[0] for status, badge in SALE_STATUS_BADGES.items()}


def _sale_product(row: dict[str, Any]) -> SaleProduct:
    return SaleProduct(
        row["id"], row["label"], row["weight_g"], row["price_local"], row["price_online"], row["price_wholesale"],
        row["is_active"],
    )  # fmt: skip


def _status_badge(status: SaleDisplayStatus) -> None:
    label, color, icon = SALE_STATUS_BADGES[status]
    st.badge(label, color=color, icon=icon)


def _option_select(container, label: str, options: tuple, labels: dict, current, key: str):
    index = options.index(current) if current in options else 0
    return container.selectbox(label, options, index=index, format_func=labels.get, key=key)


def _item_rows(detail: SaleDetail | None) -> pd.DataFrame:
    items = detail.items if detail else []
    return pd.DataFrame(
        {
            PRODUCT_COLUMN: pd.Series([item["label"] for item in items], dtype="object"),
            QUANTITY_COLUMN: pd.Series([item["quantity"] for item in items], dtype="Int64"),
        }
    )


def _parse_items(rows: pd.DataFrame, ids_by_label: dict[str, int]) -> tuple[SaleItemInput, ...]:
    items = []
    for row in rows.to_dict("records"):
        label = row[PRODUCT_COLUMN]
        if isinstance(label, str) and label in ids_by_label:
            quantity = int(row[QUANTITY_COLUMN]) if pd.notna(row[QUANTITY_COLUMN]) else 0
            items.append(SaleItemInput(ids_by_label[label], quantity))
    return tuple(items)


def _render_availability(items: list, products_by_id: dict[int, dict[str, Any]], channel: Channel) -> None:
    frame = pd.DataFrame(
        {
            "Produto": [item.label for item in items],
            "Qtd.": [item.quantity for item in items],
            "Preço (R$)": [to_float(item.unit_price) for item in items],
            "Valor (R$)": [to_float(item.amount) for item in items],
            "Em estoque": [products_by_id[item.product_id]["stock"] for item in items],
            "Disponibilidade": [
                "OK" if products_by_id[item.product_id]["stock"] >= item.quantity
                else f"Faltam {item.quantity - products_by_id[item.product_id]['stock']}"
                for item in items
            ],
        }
    )  # fmt: skip
    st.caption(f"Preços da tabela {CHANNEL_LABELS[channel].lower()}, sem edição na venda.")
    st.dataframe(style_numbers(frame, {"Preço (R$)": 2, "Valor (R$)": 2}), hide_index=True, width="stretch")


def _render_discount(products_amount: Decimal, current: Decimal, key: str) -> Decimal:
    mode_column, value_column, _ = st.columns([1, 1.4, 1.6], vertical_alignment="bottom")
    mode = mode_column.segmented_control("Desconto em", ["R$", "%"], default="R$", key=f"{key}_discount_mode")
    if mode == "%":
        pct = value_column.number_input("Desconto (%)", min_value=0.0, max_value=100.0, step=1.0, format="%.1f",
                                        key=f"{key}_discount_pct")  # fmt: skip
        return round_money(products_amount * to_decimal(pct, 1) / 100)
    amount = value_column.number_input("Desconto (R$)", min_value=0.0, step=1.0, format="%.2f",
                                       value=to_float(current) or 0.0, key=f"{key}_discount")  # fmt: skip
    return to_decimal(amount)


def _render_summary(context: SaleFormContext, items: list, data: SaleInput, customer: dict[str, Any]) -> None:
    totals = sale_totals(items, data.discount_amount, data.freight_amount)
    columns = st.columns(4)
    columns[0].metric("Produtos", format_currency(totals.products_amount))
    columns[1].metric(
        "Desconto", format_currency(totals.discount_amount), help=f"{format_decimal(discount_pct(totals), 1)}%"
    )
    columns[2].metric("Frete", format_currency(totals.freight_amount))
    columns[3].metric("Total", format_currency(totals.total_amount))
    details = [f"Peso {format_decimal(Decimal(totals.total_weight_g) / 1000, 3)} kg"]
    if data.delivery_type is DeliveryType.SHIPPING and context.shipping_box:
        boxes = box_count(totals.total_weight_g, data.delivery_type, context.shipping_box.capacity_g)
        details.append(f"{boxes} × {context.shipping_box.name}")
    terms = receivable_terms(data.payment_method, customer["payment_term_days"], context.settings)
    fee = payment_fee(totals.total_amount, terms.fee_pct)
    if fee:
        details.append(f"taxa do cartão {format_currency(fee)}")
    details.append("recebido na hora" if terms.settled_on_creation else f"recebe em {terms.due_days} dias")
    st.caption(" · ".join(details))
    if needs_discount_approval(totals, context.settings.max_discount_pct):
        st.warning(
            f"Desconto acima de {format_decimal(context.settings.max_discount_pct, 0)}%: só gerentes confirmam.",
            icon=":material/warning:",
        )


def _render_sale_form(actor: User, detail: SaleDetail | None) -> None:
    sale = detail.sale if detail else {}
    key = f"{PAGE_KEY}_{sale.get('id', 'new')}"
    context = sales_service.get_sale_form_context(actor, sale.get("customer_id"))
    if not context.products:
        st.warning("Nenhum produto ativo para vender. Cadastre os produtos primeiro.", icon=":material/warning:")
        return
    channel_column, customer_column = st.columns([1, 2])
    channel = _option_select(channel_column, "Canal", tuple(Channel), CHANNEL_LABELS,
                             Channel(sale["channel"]) if sale else Channel.LOCAL, f"{key}_channel")  # fmt: skip
    walk_in = next((row["id"] for row in context.customers if row["is_system"]), None)
    customer_id = record_selectbox(
        customer_column, "Cliente", context.customers,
        sale.get("customer_id") or (walk_in if channel is Channel.LOCAL else None),
        f"{key}_customer_{channel}", lambda row: row["name"],
    )  # fmt: skip
    rules = CHANNEL_RULES[channel]
    delivery_column, payment_column = st.columns(2)
    delivery = _option_select(
        delivery_column,
        "Entrega",
        rules.deliveries,
        DELIVERY_TYPE_LABELS,
        DeliveryType(sale["delivery_type"]) if sale else None,
        f"{key}_delivery_{channel}",
    )
    payment = _option_select(
        payment_column,
        "Pagamento",
        rules.payments,
        PAYMENT_METHOD_LABELS,
        PaymentMethod(sale["payment_method"]) if sale else None,
        f"{key}_payment_{channel}",
    )
    customer = next((row for row in context.customers if row["id"] == customer_id), None)  # fmt: skip
    address = None
    if delivery is not DeliveryType.PICKUP:
        suggested = sale.get("delivery_address") or (
            ", ".join(part for part in (customer.get("address"), customer.get("city"), customer.get("state")) if part)
            if customer else ""
        )  # fmt: skip
        address = st.text_input("Endereço de entrega", value=suggested, key=f"{key}_address_{customer_id}")
    products_by_id = {row["id"]: row for row in context.products}
    ids_by_label = {row["label"]: row["id"] for row in context.products}
    edited = st.data_editor(
        _item_rows(detail),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key=f"{key}_items",
        column_config={
            PRODUCT_COLUMN: st.column_config.SelectboxColumn(options=list(ids_by_label), required=True, width="large"),
            QUANTITY_COLUMN: st.column_config.NumberColumn(min_value=1, step=1, default=1, required=True),
        },
    )
    item_inputs = _parse_items(edited, ids_by_label)
    try:
        items = price_items(item_inputs, {pid: _sale_product(row) for pid, row in products_by_id.items()}, channel)
    except AppError as error:
        items = []
        if item_inputs:
            st.warning(str(error), icon=":material/warning:")
    if items:
        _render_availability(items, products_by_id, channel)
    products_amount = sum((item.amount for item in items), Decimal("0"))
    discount = _render_discount(products_amount, sale.get("discount_amount", Decimal("0")), key)
    freight_column, notes_column = st.columns([1, 2])
    freight = freight_column.number_input(
        "Frete cobrado (R$)", min_value=0.0, step=1.0, format="%.2f", value=to_float(sale.get("freight_amount")) or 0.0,
        disabled=delivery is DeliveryType.PICKUP, key=f"{key}_freight",
    )  # fmt: skip
    notes = notes_column.text_input("Observação", value=sale.get("notes") or "", key=f"{key}_notes")
    data = SaleInput(
        customer_id=customer_id,
        channel=channel,
        delivery_type=delivery,
        payment_method=payment,
        items=item_inputs,
        discount_amount=discount,
        freight_amount=Decimal("0") if delivery is DeliveryType.PICKUP else to_decimal(freight),
        delivery_address=address,
        notes=notes,
    )
    if items and customer:
        _render_summary(context, items, data, customer)
    if detail:
        if st.button("Salvar alterações", type="primary", icon=":material/check:"):
            _run(lambda: sales_service.update_quote(actor, sale["id"], data), f"Orçamento {sale['number']} atualizado.")
        return
    deliver_now = delivery is DeliveryType.PICKUP and st.checkbox(
        "Cliente já levou os produtos", value=True, key=f"{key}_deliver_now"
    )
    with st.container(horizontal=True):
        if st.button("Confirmar venda", type="primary", icon=":material/point_of_sale:"):
            _finish_confirmation(lambda: sales_service.create_sale(actor, data, confirm=True, deliver_now=deliver_now))
        if st.button("Salvar orçamento", icon=":material/request_quote:"):
            _run(lambda: sales_service.create_sale(actor, data), "Orçamento salvo.", show_number=True)


def _run(action, message: str, show_number: bool = False) -> None:
    try:
        result = action()
    except AppError as error:
        st.error(str(error))
        return
    finish_action(PAGE_KEY, f"Orçamento {result.number} salvo." if show_number else message)


def _margin_details(result: SaleResult) -> list[str]:
    if result.margin_pct is None:
        return []
    return [
        f"Margem ▸ receita {format_currency(result.net_revenue)} · CMV {format_currency(result.products_cost)} · "
        f"margem bruta **{format_decimal(result.margin_pct, 1)}%**"
    ]


def _finish_confirmation(action) -> None:
    try:
        result = action()
    except AppError as error:
        st.error(str(error))
        return
    title = f"Venda {result.number} confirmada."
    if result.status is SaleStatus.DELIVERED:
        title = f"Venda {result.number} confirmada e entregue."
    remember_effects(title, result.effects, _margin_details(result))
    finish_action(PAGE_KEY, title)


def _render_confirm_dialog(actor: User, detail: SaleDetail) -> None:
    sale = detail.sale
    st.markdown(
        f"Confirmar **{sale['number']}** de {sale['customer_name']} por **{format_currency(sale['total_amount'])}**? "
        "Os produtos saem do estoque e o valor vira título a receber."
    )
    deliver_now = DeliveryType(sale["delivery_type"]) is DeliveryType.PICKUP and st.checkbox(
        "Cliente já levou os produtos", value=True
    )
    sale_date = None
    if has_permission(actor, Permission.BACKDATE_OPERATIONS):
        sale_date = st.date_input("Data da venda", value=today(), min_value=sale["quote_date"], max_value=today(),
                                  format="DD/MM/YYYY")  # fmt: skip
    if st.button("Confirmar venda", type="primary", icon=":material/point_of_sale:"):
        _finish_confirmation(lambda: sales_service.confirm_sale(actor, sale["id"], deliver_now, sale_date))


def _render_ship_dialog(actor: User, detail: SaleDetail) -> None:
    sale = detail.sale
    st.markdown(f"Expedir **{sale['number']}** para {sale['delivery_address']}.")
    tracking = st.text_input("Código de rastreio", placeholder="Ex.: BR123456789")
    carrier = st.text_input("Transportadora", placeholder="Ex.: Correios")
    freight = st.number_input(
        "Custo real do frete (R$)", min_value=0.0, step=1.0, format="%.2f", value=None,
        help=f"Cobrado do cliente: {format_currency(sale['freight_amount'])}. Use zero para frete grátis do parceiro.",
    )  # fmt: skip
    if st.button("Expedir", type="primary", icon=":material/local_shipping:"):
        try:
            effects = sales_service.ship_sale(actor, sale["id"], ShipmentInput(tracking, to_decimal(freight), carrier))
        except AppError as error:
            st.error(str(error))
        else:
            remember_effects(f"Venda {sale['number']} expedida.", effects)
            finish_action(PAGE_KEY, f"Venda {sale['number']} expedida.")


def _render_deliver_dialog(actor: User, detail: SaleDetail) -> None:
    sale = detail.sale
    st.markdown(f"Registrar a entrega de **{sale['number']}** a {sale['customer_name']}?")
    if st.button("Registrar entrega", type="primary", icon=":material/check_circle:"):
        try:
            sales_service.deliver_sale(actor, sale["id"])
        except AppError as error:
            st.error(str(error))
        else:
            finish_action(PAGE_KEY, f"Venda {sale['number']} entregue.")


def _render_cancel_dialog(actor: User, detail: SaleDetail) -> None:
    sale = detail.sale
    if SaleStatus(sale["status"]) is SaleStatus.QUOTE:
        st.markdown(f"Cancelar o orçamento **{sale['number']}**? Ele não movimentou estoque nem financeiro.")
    else:
        st.markdown(
            f"Cancelar a venda **{sale['number']}**? Os produtos e as caixas voltam ao estoque pelo custo da venda, "
            "os títulos em aberto são cancelados e o que já foi recebido vira um reembolso a pagar."
        )
    reason = st.text_input("Motivo do cancelamento")
    if st.button("Cancelar venda", type="primary", icon=":material/block:"):
        try:
            effects = sales_service.cancel_sale(actor, sale["id"], reason)
        except AppError as error:
            st.error(str(error))
        else:
            if effects.stock or effects.entries:
                remember_effects(f"Venda {sale['number']} cancelada.", effects)
            finish_action(PAGE_KEY, f"Venda {sale['number']} cancelada.")


def _render_refresh(actor: User, sale: dict[str, Any]) -> None:
    try:
        sales_service.refresh_quote(actor, sale["id"])
    except AppError as error:
        st.error(str(error))
    else:
        finish_action(PAGE_KEY, f"Orçamento {sale['number']} atualizado com os preços de hoje.")


def _render_actions(actor: User, detail: SaleDetail, display: SaleDisplayStatus) -> None:
    sale = detail.sale
    status = SaleStatus(sale["status"])
    delivery = DeliveryType(sale["delivery_type"])
    can_sell = has_permission(actor, Permission.MANAGE_SALES)
    with st.container(horizontal=True):
        if (
            can_sell
            and display is SaleDisplayStatus.QUOTE
            and st.button("Confirmar venda", icon=":material/point_of_sale:")
        ):
            st.dialog("Confirmar venda")(_render_confirm_dialog)(actor, detail)
        if (
            can_sell
            and display is SaleDisplayStatus.EXPIRED
            and st.button("Atualizar preços", icon=":material/refresh:")
        ):
            _render_refresh(actor, sale)
        if can_sell and status is SaleStatus.QUOTE and st.button("Editar", icon=":material/edit:"):
            st.dialog("Editar orçamento", width="large")(_render_sale_form)(actor, detail)
        if (
            can_sell
            and status is SaleStatus.CONFIRMED
            and delivery is DeliveryType.SHIPPING
            and st.button("Expedir", icon=":material/local_shipping:")
        ):
            st.dialog("Expedir pedido")(_render_ship_dialog)(actor, detail)
        can_deliver = status is SaleStatus.SHIPPED or (
            status is SaleStatus.CONFIRMED and delivery is not DeliveryType.SHIPPING
        )
        if can_sell and can_deliver and st.button("Registrar entrega", icon=":material/check_circle:"):
            st.dialog("Registrar entrega")(_render_deliver_dialog)(actor, detail)
        can_cancel = (status is SaleStatus.QUOTE and can_sell) or (
            status is SaleStatus.CONFIRMED and has_permission(actor, Permission.CANCEL_SALES)
        )
        if can_cancel and st.button("Cancelar", icon=":material/block:"):
            st.dialog("Cancelar venda")(_render_cancel_dialog)(actor, detail)
        is_quote = status is SaleStatus.QUOTE
        if status is not SaleStatus.CANCELLED:
            st.download_button(
                "Proposta comercial" if is_quote else "Comprovante",
                data=sale_document_pdf(detail, STATUS_LABELS[display]),
                file_name=f"{sale['number']}.pdf",
                mime="application/pdf",
                icon=":material/picture_as_pdf:",
            )


def _render_margin(sale: dict[str, Any]) -> None:
    if sale["products_cost"] is None:
        return
    net_revenue = sale["products_amount"] - sale["discount_amount"]
    contribution = (
        net_revenue + sale["freight_amount"] - sale["products_cost"] - (sale["boxes_cost"] or 0)
        - (sale["actual_freight_cost"] or 0) - (sale["payment_fee"] or 0)
    )  # fmt: skip
    margin = gross_margin_pct(net_revenue, sale["products_cost"])
    columns = st.columns(4)
    columns[0].metric("Receita líquida", format_currency(net_revenue))
    columns[1].metric("CMV", format_currency(sale["products_cost"]), help="Custo dos produtos no momento da venda.")
    columns[2].metric("Margem bruta", f"{format_decimal(margin, 1)}%" if margin is not None else "—")
    columns[3].metric(
        "Margem de contribuição", format_currency(contribution),
        help="Receita líquida + frete cobrado − CMV − caixas − frete real − taxa de pagamento.",
    )  # fmt: skip


def _render_items_tab(detail: SaleDetail) -> None:
    frame = pd.DataFrame(
        {
            "Produto": [item["label"] for item in detail.items],
            "Qtd.": [item["quantity"] for item in detail.items],
            "Preço (R$)": [to_float(item["unit_price"]) for item in detail.items],
            "Valor (R$)": [to_float(item["amount"]) for item in detail.items],
            "Custo na venda (R$)": [to_float(item["unit_cost_snapshot"]) for item in detail.items],
        }
    )
    places = {"Preço (R$)": 2, "Valor (R$)": 2, "Custo na venda (R$)": 4}
    st.dataframe(style_numbers(frame, places), hide_index=True, width="stretch", placeholder="—")


def _render_entries_tab(detail: SaleDetail) -> None:
    if not detail.entries:
        st.caption("Os títulos são gerados na confirmação.")
        return
    frame = pd.DataFrame(
        {
            "Descrição": [row["description"] for row in detail.entries],
            "Tipo": ["A receber" if row["entry_type"] == "RECEIVABLE" else "A pagar" for row in detail.entries],
            "Vencimento": [row["due_date"] for row in detail.entries],
            "Valor (R$)": [to_float(row["amount"]) for row in detail.entries],
            "Situação": [ENTRY_STATUS_BADGES[EntryDisplayStatus(row["display_status"])][0] for row in detail.entries],
        }
    )
    st.dataframe(style_numbers(frame, {"Valor (R$)": 2}), hide_index=True, width="stretch",
                 column_config={"Vencimento": DATE_COLUMN})  # fmt: skip


def _render_movements_tab(detail: SaleDetail) -> None:
    if not detail.movements:
        st.caption("O estoque é baixado na confirmação.")
        return
    frame = pd.DataFrame(
        {
            "Data": [row["movement_date"] for row in detail.movements],
            "Tipo": [MOVEMENT_TYPE_LABELS[MovementType(row["movement_type"])] for row in detail.movements],
            "Item": [row["item_label"] for row in detail.movements],
            "Quantidade": [to_float(row["quantity"]) for row in detail.movements],
            "Saldo após": [to_float(row["balance_after"]) for row in detail.movements],
            "Custo unitário (R$)": [to_float(row["unit_cost"]) for row in detail.movements],
        }
    )
    places = {"Quantidade": 0, "Saldo após": 0, "Custo unitário (R$)": 4}
    st.dataframe(style_numbers(frame, places), hide_index=True, width="stretch", column_config={"Data": DATE_COLUMN})


def _render_timeline_tab(detail: SaleDetail) -> None:
    for event in detail.events:
        label = STATUS_LABELS[SaleDisplayStatus(event["to_status"])]
        line = f"**{label}** · {format_datetime(event['created_at'])} · {event['user_email']}"
        if event["notes"]:
            line += f" · {event['notes']}"
        st.markdown(f"- {line}")


def _render_detail(actor: User, sale_id: int) -> None:
    try:
        detail = sales_service.get_sale_detail(actor, sale_id)
    except AppError as error:
        st.error(str(error))
        return
    sale = detail.sale
    display = SaleDisplayStatus(sale["display_status"])
    with st.container(border=True):
        title_column, badge_column = st.columns([4, 1], vertical_alignment="center")
        title_column.subheader(sale["number"])
        with badge_column:
            _status_badge(display)
        history = detail.customer_history
        summary = f"**{sale['customer_name']}**"
        if history["order_count"]:
            summary += (
                f" · {history['order_count']} pedido(s), {format_currency(history['total_spent'])} no total, último em "
                f"{history['last_sale_date']:%d/%m/%Y}"
            )
        st.markdown(summary)
        columns = st.columns(4)
        columns[0].markdown(f"**Canal**  \n{CHANNEL_LABELS[Channel(sale['channel'])]}")
        columns[1].markdown(f"**Entrega**  \n{DELIVERY_TYPE_LABELS[DeliveryType(sale['delivery_type'])]}")
        columns[2].markdown(f"**Pagamento**  \n{PAYMENT_METHOD_LABELS[PaymentMethod(sale['payment_method'])]}")
        columns[3].markdown(f"**Total**  \n{format_currency(sale['total_amount'])}")
        dates = [f"Orçamento em {sale['quote_date']:%d/%m/%Y}"]
        if sale["status"] == SaleStatus.QUOTE:
            dates.append(f"válido até {sale['quote_valid_until']:%d/%m/%Y}")
        if sale["sale_date"]:
            dates.append(f"vendido em {sale['sale_date']:%d/%m/%Y}")
        if sale["tracking_code"]:
            dates.append(f"rastreio {sale['tracking_code']}")
        if sale["delivery_address"]:
            dates.append(sale["delivery_address"])
        st.caption(" · ".join(dates))
        if sale["cancel_reason"]:
            st.caption(f"Motivo do cancelamento: {sale['cancel_reason']}")
        _render_margin(sale)
        _render_actions(actor, detail, display)
        items_tab, entries_tab, movements_tab, timeline_tab = st.tabs(
            ["Itens", "Financeiro", "Estoque", "Linha do tempo"]
        )
        with items_tab:
            _render_items_tab(detail)
        with entries_tab:
            _render_entries_tab(detail)
        with movements_tab:
            _render_movements_tab(detail)
        with timeline_tab:
            _render_timeline_tab(detail)


def _render_filters(actor: User) -> SaleFilters:
    period_column, customer_column, action_column = st.columns([1.4, 1.6, 1], vertical_alignment="bottom")
    start, end = period_input(period_column, "Período", f"{PAGE_KEY}_period", 30)
    customer_id = record_selectbox(
        customer_column, "Cliente", sales_service.get_customer_options(actor), None, f"{PAGE_KEY}_customer",
        lambda row: row["name"], placeholder="Todos",
    )  # fmt: skip
    if has_permission(actor, Permission.MANAGE_SALES) and action_column.button(
        "Nova venda", type="primary", icon=":material/add:", width="stretch"
    ):
        st.dialog("Nova venda", width="large")(_render_sale_form)(actor, None)
    channel_column, status_column = st.columns([1, 2])
    channels = channel_column.pills(
        "Canal", list(Channel), selection_mode="multi", default=list(Channel), format_func=CHANNEL_LABELS.get,
        key=f"{PAGE_KEY}_channels",
    )  # fmt: skip
    statuses = status_column.multiselect(
        "Situação", list(SaleDisplayStatus), default=DEFAULT_STATUSES, format_func=STATUS_LABELS.get,
        key=f"{PAGE_KEY}_statuses",
    )  # fmt: skip
    return SaleFilters(start, end, tuple(channels or Channel), tuple(statuses or SaleDisplayStatus), customer_id)


def _sales_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Número": [row["number"] for row in rows],
            "Data": [row["sale_date"] or row["quote_date"] for row in rows],
            "Cliente": [row["customer_name"] for row in rows],
            "Canal": [CHANNEL_LABELS[Channel(row["channel"])] for row in rows],
            "Entrega": [DELIVERY_TYPE_LABELS[DeliveryType(row["delivery_type"])] for row in rows],
            "Pagamento": [PAYMENT_METHOD_LABELS[PaymentMethod(row["payment_method"])] for row in rows],
            "Total (R$)": [to_float(row["total_amount"]) for row in rows],
            "Situação": [STATUS_LABELS[SaleDisplayStatus(row["display_status"])] for row in rows],
        }
    )


def _render_metrics(rows: list[dict[str, Any]]) -> None:
    invoiced = [row for row in rows if SaleDisplayStatus(row["display_status"]) in INVOICED]
    revenue = sum((row["total_amount"] for row in invoiced), Decimal("0"))
    quotes = [row for row in rows if row["display_status"] == SaleDisplayStatus.QUOTE]
    columns = st.columns(4)
    columns[0].metric("Faturado", format_currency(revenue))
    columns[1].metric("Vendas", len(invoiced))
    columns[2].metric("Ticket médio", format_currency(revenue / len(invoiced)) if invoiced else "—")
    columns[3].metric("Orçamentos abertos", len(quotes))
    late = [
        row["number"]
        for row in rows
        if is_late_shipment(SaleStatus(row["status"]), DeliveryType(row["delivery_type"]), row["sale_date"], today())
    ]
    if late:
        st.warning(
            f"Pedidos confirmados há mais de {LATE_SHIPPING_DAYS} dias sem expedição: {', '.join(late)}.",
            icon=":material/schedule:",
        )


def render_sales_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Vendas")
    st.caption("Orçamentos e pedidos dos três canais. A confirmação baixa o estoque e gera os títulos a receber.")
    show_effects()
    filters = _render_filters(actor)
    try:
        rows = sales_service.list_sales(actor, filters)
    except AppError as error:
        st.error(str(error))
        return
    if not rows:
        st.info("Nenhuma venda no período e nos filtros escolhidos.", icon=":material/info:")
        return
    _render_metrics(rows)
    version = st.session_state.get(f"{PAGE_KEY}_table_version", 0)
    event = st.dataframe(
        style_numbers(_sales_table(rows), {"Total (R$)": 2}),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        column_config={"Data": DATE_COLUMN},
        key=f"{PAGE_KEY}_table_{version}",
    )
    selected = event.selection.rows
    if selected and selected[0] < len(rows):
        _render_detail(actor, rows[selected[0]]["id"])
    else:
        st.caption("Selecione uma venda para ver os itens, os títulos, a linha do tempo e as ações.")
