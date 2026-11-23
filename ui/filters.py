from datetime import date, timedelta

from streamlit.delta_generator import DeltaGenerator

from core.clock import today


def period_input(container: DeltaGenerator, label: str, key: str, days: int) -> tuple[date, date]:
    period = container.date_input(label, value=(today() - timedelta(days=days), today()), format="DD/MM/YYYY", key=key)
    return (period[0], period[1]) if len(period) == 2 else (period[0], period[0])
