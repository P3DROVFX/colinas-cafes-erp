from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st

from core.clock import today
from core.errors import AppError
from domain.access import Permission, User, has_permission
from domain.catalog import RoastProfile
from domain.dates import add_months
from domain.inventory import StockItemKind, format_quantity
from domain.numbers import format_decimal
from domain.production import PackingInput, packed_coffee_unit_cost, packing_consumed_kg
from services import production as production_service
from services.production import PackingMaterials, PeriodFilters
from ui.effects import remember_effects, show_effects
from ui.feedback import show_flash
from ui.filters import period_input
from ui.formatting import style_numbers, to_float
from ui.forms import record_selectbox
from ui.labels import ROAST_PROFILE_LABELS
from ui.records import finish_action
from ui.session import get_session_user

PAGE_KEY = "packing"
DATE_COLUMN = st.column_config.DateColumn(format="DD/MM/YYYY")


def _unit_cost(value: Decimal) -> str:
    return f"R$ {format_decimal(value, 4)}"


def _batch_option(batch: dict[str, Any]) -> str:
    return f"{batch['code']} · {format_decimal(batch['stock_kg'], 3)} kg · torrado há {batch['days_since_roast']} dias"


def _render_requirements(batch: dict[str, Any], materials: PackingMaterials, bag_count: int, weight_g: int) -> None:
    count = Decimal(bag_count)
    rows = [
        ("Café torrado", batch["code"], StockItemKind.ROAST_BATCH, batch["stock_kg"],
         packing_consumed_kg(bag_count, weight_g)),
        ("Pacote", materials.bag.label, StockItemKind.PACKAGING_ITEM, materials.bag.stock, count),
        ("Etiqueta", materials.label.label, StockItemKind.PACKAGING_ITEM, materials.label.stock, count),
    ]  # fmt: skip
    frame = pd.DataFrame(
        {
            "Material": [row[0] for row in rows],
            "Item": [row[1] for row in rows],
            "Necessário": [format_quantity(row[2], row[4]) for row in rows],
            "Disponível": [format_quantity(row[2], row[3]) for row in rows],
            "Situação": ["OK" if row[3] >= row[4] else f"Faltam {format_quantity(row[2], row[4] - row[3])}"
                         for row in rows],
        }
    )  # fmt: skip
    st.dataframe(frame, hide_index=True, width="stretch")


def _render_packing_form(actor: User) -> None:
    products = production_service.list_packable_products(actor)
    if not products:
        st.warning("Nenhum produto ativo. Cadastre o produto em Cadastros › Produtos.", icon=":material/warning:")
        return
    products_by_id = {product["id"]: product for product in products}
    product_id = record_selectbox(
        st, "Produto", products, None, f"{PAGE_KEY}_product", lambda product: product["label"]
    )
    if product_id is None:
        st.info("Escolha o produto para listar os lotes torrados compatíveis.", icon=":material/info:")
        return
    product = products_by_id[product_id]
    batches = production_service.list_compatible_batches(actor, product_id)
    if not batches:
        profile = ROAST_PROFILE_LABELS[RoastProfile(product["roast_profile"])].lower()
        st.warning(
            f"Nenhum lote aberto deste café com torra {profile}. Registre uma torra compatível antes de envasar.",
            icon=":material/warning:",
        )
        return
    batches_by_id = {batch["id"]: batch for batch in batches}
    batch_id = st.selectbox(
        "Lote torrado",
        list(batches_by_id),
        index=0,
        format_func=lambda option: _batch_option(batches_by_id[option]),
        key=f"{PAGE_KEY}_batch_{product_id}",
        help="Só aparecem lotes abertos do mesmo café e perfil do produto, do mais antigo para o mais novo.",
    )
    batch = batches_by_id[batch_id]
    left, right = st.columns(2)
    bag_count = left.number_input("Pacotes", min_value=1, step=1, value=1, key=f"{PAGE_KEY}_count")
    packing_date = None
    if has_permission(actor, Permission.BACKDATE_OPERATIONS):
        packing_date = right.date_input(
            "Data do envase", value=today(), min_value=batch["roast_date"], max_value=today(), format="DD/MM/YYYY"
        )
    materials = production_service.get_packing_materials(actor, product_id)
    _render_requirements(batch, materials, int(bag_count), product["weight_g"])
    coffee_cost = packed_coffee_unit_cost(
        product["weight_g"], batch["green_weight_kg"], batch["green_cost_per_kg"], batch["roasted_weight_kg"]
    )
    unit_cost = coffee_cost + materials.bag.unit_cost + materials.label.unit_cost
    expiry = add_months(packing_date or today(), materials.shelf_life_months)
    st.markdown(
        f"Custo do pacote: **{_unit_cost(unit_cost)}** (café {_unit_cost(coffee_cost)} + pacote "
        f"{_unit_cost(materials.bag.unit_cost)} + etiqueta {_unit_cost(materials.label.unit_cost)}) · "
        f"validade **{expiry:%d/%m/%Y}**"
    )
    if st.button("Registrar envase", type="primary", icon=":material/check:"):
        try:
            result = production_service.pack(actor, PackingInput(product_id, batch_id, int(bag_count)), packing_date)
        except AppError as error:
            st.error(str(error))
        else:
            details = [f"Custo do pacote **{_unit_cost(result.unit_cost)}** · validade {result.expiry_date:%d/%m/%Y}"]
            if result.batch_closed:
                details.append(f"O lote {batch['code']} zerou e foi encerrado.")
            remember_effects(f"Envase {result.code} registrado.", result.effects, details)
            finish_action(PAGE_KEY, f"Envase {result.code} registrado.")


def _packings_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Envase": [row["code"] for row in rows],
            "Produto": [row["product_sku"] for row in rows],
            "Lote torrado": [row["roast_batch_code"] for row in rows],
            "Data": [row["packing_date"] for row in rows],
            "Validade": [row["expiry_date"] for row in rows],
            "Pacotes": [row["bag_count"] for row in rows],
            "Consumo (kg)": [to_float(row["consumed_kg"]) for row in rows],
            "Café (R$)": [to_float(row["coffee_unit_cost"]) for row in rows],
            "Pacote (R$)": [to_float(row["bag_unit_cost"]) for row in rows],
            "Etiqueta (R$)": [to_float(row["label_unit_cost"]) for row in rows],
            "Custo unitário (R$)": [to_float(row["unit_cost"]) for row in rows],
            "Dias desde a torra": [row["days_since_roast"] for row in rows],
        }
    )


def render_packing_page() -> None:
    actor = get_session_user()
    show_flash()
    st.title("Envases")
    st.caption(
        "Cada envase baixa o café torrado, os pacotes e as etiquetas e coloca os pacotes prontos no estoque do produto."
    )
    show_effects()
    period_column, action_column = st.columns([3, 1], vertical_alignment="bottom")
    start, end = period_input(period_column, "Período do envase", f"{PAGE_KEY}_period", 90)
    if has_permission(actor, Permission.MANAGE_PRODUCTION) and action_column.button(
        "Novo envase", type="primary", icon=":material/add:", width="stretch"
    ):
        st.dialog("Novo envase", width="large")(_render_packing_form)(actor)
    try:
        rows = production_service.list_packing_batches(actor, PeriodFilters(start, end))
    except AppError as error:
        st.error(str(error))
        return
    if not rows:
        st.info("Nenhum envase no período.", icon=":material/info:")
        return
    places = {"Consumo (kg)": 3, "Café (R$)": 4, "Pacote (R$)": 4, "Etiqueta (R$)": 4, "Custo unitário (R$)": 4}
    st.dataframe(
        style_numbers(_packings_table(rows), places),
        hide_index=True,
        width="stretch",
        placeholder="—",
        column_config={"Data": DATE_COLUMN, "Validade": DATE_COLUMN},
    )
