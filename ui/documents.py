from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from domain.finance import EntryType
from domain.inventory import StockItemKind, format_quantity
from domain.numbers import format_decimal
from domain.purchasing import PurchaseStatus
from domain.sales import Channel, DeliveryType, PaymentMethod, SaleDisplayStatus
from services.purchases import PurchaseDetail
from services.sales import SaleDetail
from ui.formatting import format_currency, format_document
from ui.labels import CHANNEL_LABELS, DELIVERY_TYPE_LABELS, PAYMENT_METHOD_LABELS, PURCHASE_STATUS_BADGES

COMPANY_NAME = "Colinas Cafés"
COMPANY_DETAILS = "Microtorrefação de cafés especiais · Garanhuns - PE"
FOOTER = "Documento sem valor fiscal, emitido pelo sistema de gestão da Colinas Cafés."
LATIN1_REPLACEMENTS = str.maketrans({"–": "-", "—": "-", "→": "->", "’": "'", "“": '"', "”": '"'})


def _text(value: object) -> str:
    """Core PDF fonts only cover Latin-1, which already includes every Portuguese accent."""
    return str(value).translate(LATIN1_REPLACEMENTS).encode("latin-1", "replace").decode("latin-1")


class _Document(FPDF):
    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, _text(FOOTER), align="C")

    def line_text(self, text: str, size: int = 10, style: str = "", height: float = 6) -> None:
        self.set_font("Helvetica", style, size)
        self.multi_cell(0, height, _text(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def header_block(self, title: str, number: str, status: str) -> None:
        self.line_text(COMPANY_NAME, 18, "B", 9)
        self.line_text(COMPANY_DETAILS, 9)
        self.ln(4)
        self.line_text(f"{title} {number}", 14, "B", 8)
        self.line_text(f"Situação: {status}", 10)
        self.ln(2)

    def rows_table(self, headings: Sequence[str], rows: Sequence[Sequence[str]], widths: Sequence[int]) -> None:
        self.set_font("Helvetica", "", 9)
        alignments = ["LEFT"] + ["RIGHT"] * (len(headings) - 1)
        with self.table(col_widths=widths, text_align=alignments, line_height=6) as table:
            table.row([_text(heading) for heading in headings])
            for row in rows:
                table.row([_text(cell) for cell in row])
        self.ln(3)

    def totals_block(self, lines: Sequence[tuple[str, str]]) -> None:
        for index, (label, value) in enumerate(lines):
            style = "B" if index == len(lines) - 1 else ""
            self.set_font("Helvetica", style, 10)
            self.cell(150, 6, _text(label), align="R")
            self.cell(0, 6, _text(value), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(3)


def _date(value: date | None) -> str:
    return f"{value:%d/%m/%Y}" if value else "—"


def _unit_cost(value: Decimal) -> str:
    return f"R$ {format_decimal(value, 4)}"


def sale_document_pdf(detail: SaleDetail, status_label: str) -> bytes:
    """Commercial proposal for quotes and non-fiscal receipt from confirmation on (RF-VEN-07)."""
    sale = detail.sale
    is_quote = SaleDisplayStatus(sale["display_status"]) in (SaleDisplayStatus.QUOTE, SaleDisplayStatus.EXPIRED)
    pdf = _Document()
    pdf.add_page()
    pdf.header_block("Proposta comercial" if is_quote else "Comprovante de venda", sale["number"], status_label)
    customer = sale["customer_name"]
    if sale["customer_document"]:
        customer += f" · {format_document(sale['customer_document'])}"
    pdf.line_text(f"Cliente: {customer}")
    if is_quote:
        pdf.line_text(f"Data: {_date(sale['quote_date'])} · válida até {_date(sale['quote_valid_until'])}")
    else:
        pdf.line_text(f"Data da venda: {_date(sale['sale_date'])}")
    pdf.line_text(
        f"Canal: {CHANNEL_LABELS[Channel(sale['channel'])]} · Entrega: "
        f"{DELIVERY_TYPE_LABELS[DeliveryType(sale['delivery_type'])]} · Pagamento: "
        f"{PAYMENT_METHOD_LABELS[PaymentMethod(sale['payment_method'])]}"
    )
    if sale["delivery_address"]:
        pdf.line_text(f"Endereço de entrega: {sale['delivery_address']}")
    if sale["tracking_code"]:
        pdf.line_text(f"Rastreio: {sale['tracking_code']}" + (f" ({sale['carrier']})" if sale["carrier"] else ""))
    pdf.ln(3)
    pdf.rows_table(
        ("Produto", "Qtd.", "Preço unitário", "Valor"),
        [
            (item["label"], str(item["quantity"]), format_currency(item["unit_price"]), format_currency(item["amount"]))
            for item in detail.items
        ],
        (100, 20, 35, 35),
    )
    pdf.totals_block(
        [
            ("Produtos", format_currency(sale["products_amount"])),
            ("Desconto", f"- {format_currency(sale['discount_amount'])}"),
            ("Frete", format_currency(sale["freight_amount"])),
            ("Total", format_currency(sale["total_amount"])),
        ]
    )
    receivables = [
        entry for entry in detail.entries
        if entry["entry_type"] == EntryType.RECEIVABLE and entry["status"] != "CANCELLED"
    ]  # fmt: skip
    for entry in receivables:
        situation = f"pago em {_date(entry['settled_date'])}" if entry["status"] == "SETTLED" else "a receber"
        pdf.line_text(f"Vencimento {_date(entry['due_date'])}: {format_currency(entry['amount'])} ({situation})")
    if sale["notes"]:
        pdf.line_text(f"Observação: {sale['notes']}")
    return bytes(pdf.output())


def purchase_order_pdf(detail: PurchaseDetail) -> bytes:
    """Purchase order sent to the supplier (RF-COM-06)."""
    purchase = detail.purchase
    pdf = _Document()
    pdf.add_page()
    status = PURCHASE_STATUS_BADGES[PurchaseStatus(purchase["status"])][0]
    pdf.header_block("Pedido de compra", purchase["number"], status)
    pdf.line_text(f"Fornecedor: {purchase['supplier_name']}")
    pdf.line_text(
        f"Data do pedido: {_date(purchase['order_date'])} · Previsão de entrega: {_date(purchase['expected_date'])}"
    )
    if purchase["received_date"]:
        pdf.line_text(f"Recebido em: {_date(purchase['received_date'])}")
    if purchase["supplier_invoice"]:
        pdf.line_text(f"NF do fornecedor: {purchase['supplier_invoice']}")
    pdf.ln(3)
    pdf.rows_table(
        ("Item", "Quantidade", "Custo unitário", "Valor"),
        [
            (
                item["item_label"],
                format_quantity(StockItemKind(item["item_kind"]), item["quantity"]),
                _unit_cost(item["unit_cost"]),
                format_currency(item["quantity"] * item["unit_cost"]),
            )
            for item in detail.items
        ],
        (95, 30, 35, 30),
    )
    pdf.totals_block(
        [
            ("Produtos", format_currency(purchase["products_amount"])),
            ("Frete", format_currency(purchase["freight_amount"])),
            ("Total", format_currency(purchase["total_amount"])),
        ]
    )
    pdf.line_text(
        f"Pagamento em {purchase['installments']}x, primeira parcela {purchase['first_due_days']} dias após o "
        "recebimento e as demais a cada 30 dias."
    )
    if purchase["notes"]:
        pdf.line_text(f"Observação: {purchase['notes']}")
    return bytes(pdf.output())
