from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any

from streamlit.delta_generator import DeltaGenerator

from domain.brazil import STATES


def form_key(entity: str, record: dict[str, Any] | None) -> str:
    return f"{entity}_{record['id'] if record else 'new'}"


def index_of[Option](options: Sequence[Option], value: Option | None) -> int | None:
    return options.index(value) if value in options else None


def to_decimal(value: float | None, places: int = 2) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(value, places)))


def enum_selectbox[Option](
    container: DeltaGenerator,
    label: str,
    labels: dict[Option, str],
    value: Any,
    key: str,
    disabled: bool = False,
) -> Option:
    options = list(labels)
    current = next((option for option in options if option == value), options[0])
    return container.selectbox(
        label, options, index=options.index(current), format_func=labels.get, key=key, disabled=disabled
    )


def state_selectbox(container: DeltaGenerator, value: str | None, key: str, label: str = "UF") -> str | None:
    return container.selectbox(label, STATES, index=index_of(STATES, value), placeholder="Selecione", key=key)


def record_selectbox(
    container: DeltaGenerator,
    label: str,
    options: list[dict[str, Any]],
    value: int | None,
    key: str,
    format_option: Callable[[dict[str, Any]], str],
    disabled: bool = False,
    placeholder: str = "Selecione",
) -> int | None:
    by_id = {option["id"]: option for option in options}
    ids = list(by_id)
    return container.selectbox(
        label,
        ids,
        index=index_of(ids, value),
        format_func=lambda option_id: format_option(by_id[option_id]),
        placeholder=placeholder,
        key=key,
        disabled=disabled,
    )
