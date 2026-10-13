"""Extrae filas COMPRA/VENTA de exports PDF Inversis/MyInvestor (consulta operaciones)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.myinvestor.trades.parse_trade import parse_decimal_amount

# Inversis pypdf: a veces todo pegado, a veces con espacios (ITALIANO COMPRA, 2EUR 483,700 967,40).
_WS = r"\s*"
_TRADE_ROW_RE = re.compile(
    r"(?P<tx_date>\d{2}/\d{2}/\d{4})"
    r"(?P<liq_date>\d{2}/\d{2}/\d{4})"
    r"(?P<transaccion>\d+)"
    r"CONT\.\ ITALIANO"
    f"{_WS}"
    r"(?P<side>COMPRA|VENTA)"
    f"{_WS}"
    r"(?P<isin>[A-Z]{2}[A-Z0-9]{10})"
    f"{_WS}"
    r"(?P<name>[A-Z][A-Z0-9\s\.&\-]+?)"
    f"{_WS}"
    r"(?P<units>\d+)"
    f"{_WS}"
    r"(?P<currency>[A-Z]{3})"
    f"{_WS}"
    r"(?P<net_price>\d+,\d{3})"
    f"{_WS}"
    r"(?P<net_amount>\d+,\d{2})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InversisTradeRow:
    transaction_date: date
    """Primera fecha de la fila PDF (fecha de transacción / operación)."""
    settlement_date: date
    """Segunda fecha (liquidación); no se guarda en asset_transactions."""
    transaccion: str
    side: str
    isin: str
    instrument_name: str
    units: Decimal
    currency: str
    net_price: Decimal
    net_amount: Decimal
    source_pdf: str


def _parse_date(raw: str) -> date:
    return date.fromisoformat(
        "-".join(
            (
                raw[6:10],
                raw[3:5],
                raw[0:2],
            )
        )
    )


def parse_inversis_operations_text(text: str, *, source_pdf: str = "") -> list[InversisTradeRow]:
    """Parsea el texto plano del PDF; ignora dividendos y cabeceras."""
    rows: list[InversisTradeRow] = []
    for match in _TRADE_ROW_RE.finditer(text.replace("\xa0", " ")):
        side = match.group("side").upper()
        rows.append(
            InversisTradeRow(
                transaction_date=_parse_date(match.group("tx_date")),
                settlement_date=_parse_date(match.group("liq_date")),
                transaccion=match.group("transaccion"),
                side=side,
                isin=match.group("isin").upper(),
                instrument_name=re.sub(r"\s+", " ", match.group("name")).strip(),
                units=parse_decimal_amount(match.group("units")),
                currency=match.group("currency").upper(),
                net_price=parse_decimal_amount(match.group("net_price")),
                net_amount=parse_decimal_amount(match.group("net_amount")),
                source_pdf=source_pdf,
            )
        )
    rows.sort(key=lambda row: (row.transaction_date, row.transaccion))
    return rows


def extract_text_from_pdf(pdf_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise SystemExit(
            "Falta la dependencia 'pypdf'. Instala con: pip install pypdf"
        ) from exc

    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_inversis_pdf(pdf_path: Path) -> list[InversisTradeRow]:
    text = extract_text_from_pdf(pdf_path)
    return parse_inversis_operations_text(text, source_pdf=pdf_path.name)
