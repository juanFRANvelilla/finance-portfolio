"""Extrae filas COMPRA/VENTA de exports PDF Inversis/MyInvestor (consulta operaciones)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.myinvestor.trades.parse_trade import parse_decimal_amount

_WS = r"\s*"
_MARKET = r"(?:CONT\.\ ITALIANO|XETRA|NYSE|PAR[IÍ]S|FONDOS\s+EXTRANJEROS)"

_TRADE_LINE_RE = re.compile(
    r"^(?P<tx_date>\d{2}/\d{2}/\d{4})"
    r"(?P<liq_date>\d{2}/\d{2}/\d{4})"
    r"(?P<transaccion>\d+)"
    rf"{_MARKET}"
    f"{_WS}"
    r"(?P<side>COMPRA|VENTA|SUSCRIPCION|REEMBOLSO)"
    f"{_WS}"
    r"(?P<isin>[A-Z]{2}[A-Z0-9]{10})"
    r"(?P<rest>.+)$",
    re.IGNORECASE,
)

_FUND_UNITS_CUR_TAIL_RE = re.compile(
    r"(?P<units>\d+,\d+)(?P<currency>EUR|USD)(?P<tail>[\d,\s]+)$",
    re.IGNORECASE,
)

_REST_RE = re.compile(
    r"^(?P<name>.+?)"
    r"(?P<units>\d+)"
    f"{_WS}"
    r"(?P<currency>EUR|USD)"
    f"{_WS}"
    r"(?P<tail>[\d,\s]+)$",
    re.IGNORECASE,
)

# Diagnóstico verbose en import_transactions
_TRADE_ROW_RE = _TRADE_LINE_RE


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


def _split_price_amount(tail: str, *, units: Decimal) -> tuple[str, str] | None:
    """Separa precio e importe; valida units×precio≈importe (PDF Inversis suele pegarlos)."""
    raw = tail.strip()
    candidates: list[tuple[str, str]] = []

    if " " in raw:
        left, right = raw.rsplit(" ", 1)
        right_compact = re.sub(r"\s+", "", right)
        if re.fullmatch(r"\d+,\d{2}", right_compact):
            candidates.append((left.strip(), right_compact))

    compact = re.sub(r"\s+", "", raw)
    for split_at in range(1, len(compact)):
        amount = compact[split_at:]
        if not re.fullmatch(r"\d+,\d{2}", amount):
            continue
        price = compact[:split_at].rstrip(",")
        if price and re.search(r"\d", price):
            candidates.append((price, amount))

    # Quitar duplicados conservando orden
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for item in candidates:
        if item not in seen:
            seen.add(item)
            unique.append(item)

    if not unique:
        return None

    tolerance = Decimal("0.06")
    best: tuple[str, str] | None = None
    best_diff: Decimal | None = None
    for price_raw, amount_raw in unique:
        try:
            price = parse_decimal_amount(price_raw)
            amount = parse_decimal_amount(amount_raw)
        except Exception:
            continue
        diff = abs(units * price - amount)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best = (price_raw, amount_raw)

    if best is None or best_diff is None:
        return None
    try:
        amount_ref = parse_decimal_amount(best[1])
    except Exception:
        return None
    # Fondos: precio redondeado en PDF (p. ej. 14,146 × 14,13 ≈ 199,88 vs 200,00).
    allowed = max(tolerance, amount_ref * Decimal("0.00065"))
    if best_diff > allowed:
        return None
    return best


def _normalize_side(raw: str) -> str:
    upper = raw.upper()
    if upper == "SUSCRIPCION":
        return "COMPRA"
    if upper == "REEMBOLSO":
        return "VENTA"
    return upper


def _normalize_fund_rest_text(rest: str) -> str:
    """Ajusta ' SEUR ' (clase S + divisa) y participaciones pegadas a EUR."""
    text = rest.strip()
    text = re.sub(r"\s+SEUR\s+", " S ", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(\d+,\d+)EUR\s+",
        r"\1 EUR ",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _parse_fund_rest(rest: str) -> tuple[str, Decimal, str, Decimal, Decimal] | None:
    """Fondos: participaciones con coma (31,74000000) + EUR + precio/importe neto."""
    rest = _normalize_fund_rest_text(rest)
    compact = re.sub(r"\s+", "", rest)
    best_row: tuple[str, Decimal, str, Decimal, Decimal] | None = None
    best_diff: Decimal | None = None

    for match in _FUND_UNITS_CUR_TAIL_RE.finditer(compact):
        units = parse_decimal_amount(match.group("units"))
        split = _split_price_amount(match.group("tail"), units=units)
        if split is None:
            continue
        price_raw, amount_raw = split
        price = parse_decimal_amount(price_raw)
        amount = parse_decimal_amount(amount_raw)
        diff = abs(units * price - amount)
        if best_diff is not None and diff >= best_diff:
            continue
        units_token = match.group("units")
        name = rest
        idx = rest.replace(" ", "").find(units_token)
        if idx > 0:
            name = rest[:idx]
        name = re.sub(r"\s+", " ", name).strip()
        best_diff = diff
        best_row = (
            name,
            units,
            match.group("currency").upper(),
            price,
            amount,
        )

    return best_row


def _parse_rest(rest: str) -> tuple[str, Decimal, str, Decimal, Decimal] | None:
    rest = rest.strip()
    match = _REST_RE.match(rest)
    if match:
        units = parse_decimal_amount(match.group("units"))
        split = _split_price_amount(match.group("tail"), units=units)
        if split is None:
            return _parse_fund_rest(rest)
        price_raw, amount_raw = split
        return (
            re.sub(r"\s+", " ", match.group("name")).strip(),
            units,
            match.group("currency").upper(),
            parse_decimal_amount(price_raw),
            parse_decimal_amount(amount_raw),
        )
    return _parse_fund_rest(rest)


def parse_inversis_operations_text(text: str, *, source_pdf: str = "") -> list[InversisTradeRow]:
    """Parsea el texto plano del PDF; ignora dividendos y cabeceras."""
    normalized = text.replace("\xa0", " ")
    rows: list[InversisTradeRow] = []
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line or "DIVIDENDO" in line.upper():
            continue
        match = _TRADE_LINE_RE.match(line)
        if not match:
            continue
        parsed = _parse_rest(match.group("rest"))
        if parsed is None:
            continue
        name, units, currency, net_price, net_amount = parsed
        if units <= 0:
            continue
        rows.append(
            InversisTradeRow(
                transaction_date=_parse_date(match.group("tx_date")),
                settlement_date=_parse_date(match.group("liq_date")),
                transaccion=match.group("transaccion"),
                side=_normalize_side(match.group("side")),
                isin=match.group("isin").upper(),
                instrument_name=name,
                units=units,
                currency=currency,
                net_price=net_price,
                net_amount=net_amount,
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
