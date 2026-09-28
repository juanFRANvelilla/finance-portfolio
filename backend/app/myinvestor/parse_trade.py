"""Parser de confirmaciones de operación de valores de MyInvestor."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

MONEY_QUANT = Decimal("0.00000001")

# Valores cotizados (NYSE, PARIS, …): nombre - TICKER [US] + ISIN
_INSTRUMENT_LISTED_RE = re.compile(
    r"Mercado\s+Valor\s+"
    r"(?P<market>[A-Z0-9]{2,})\s+"
    r"(?P<name>.+?)\s+-\s+"
    r"(?P<ticker>[A-Z0-9][A-Z0-9.]*)"
    r"(?:\s+[A-Z]{2})?"
    r"\s+C[oó]digo\s+ISIN:\s*"
    r"(?P<isin>[A-Z]{2}[A-Z0-9]{10})",
    re.IGNORECASE | re.DOTALL,
)
# Fondos: FONDOS EXTR + nombre (sin ticker) + ISIN
_INSTRUMENT_FUND_RE = re.compile(
    r"Mercado\s+Valor\s+"
    r"(?P<market>FONDOS\s+EXTR)\s+"
    r"(?P<name>.+?)\s-\s*"
    r"C[oó]digo\s+ISIN:\s*"
    r"(?P<isin>[A-Z]{2}[A-Z0-9]{10})",
    re.IGNORECASE | re.DOTALL,
)

_OPERATION_RE = re.compile(
    r"\b(COMPRA|VENTA|SUSCRIPCION(?:\s+I\.I\.C\.)?)\s+(\d+/\d+)\b",
    re.IGNORECASE,
)
_DATES_LISTED_RE = re.compile(
    r"(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})"
)
_DATES_FUND_RE = re.compile(
    r"Fecha Operaci[oó]n\s+Fecha Valor\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_AMOUNTS_RE = re.compile(
    r"N[uú]mero de t[ií]tulos/Participaciones\s+Precio Bruto\s+Importe Bruto\s+"
    r"([\d.,]+)\s+([\d.,]+)\s+([A-Z]{3})\s+([\d.,]+)\s+([A-Z]{3})",
    re.IGNORECASE,
)
_FEES_RE = re.compile(
    r"Comisiones\s+Gastos\s+Tasas e Impuestos\s+"
    r"([\d.,]+)\s+([A-Z]{3})\s+([\d.,]+)\s+([A-Z]{3})\s+([\d.,]+)\s+([A-Z]{3})",
    re.IGNORECASE,
)
# BABA: neto en divisa operación + liquidación en otra divisa (4 pares tras la cabecera)
_NET_FX_RE = re.compile(
    r"Importe Efectivo Neto(?:\s*\(1\))?\s+"
    r"([\d.,]+)\s+([A-Z]{3})\s+"
    r"([\d.,]+)\s+([A-Z]{3})\s+"
    r"([\d.,]+)\s+([A-Z]{3})\s+"
    r"([\d.,]+)\s+([A-Z]{3})",
    re.IGNORECASE,
)
# Oro / ETF en EUR: retenciones + neto (3 pares)
_NET_EUR_ONLY_RE = re.compile(
    r"Importe Efectivo Neto(?:\s*\(1\))?\s+"
    r"([\d.,]+)\s+([A-Z]{3})\s+"
    r"([\d.,]+)\s+([A-Z]{3})\s+"
    r"([\d.,]+)\s+([A-Z]{3})",
    re.IGNORECASE,
)
# Fondos: cabecera incluye Tipo de Cambio y la fila de datos trae 4 importes
_NET_FUND_RE = re.compile(
    r"Importe Efectivo Neto(?:\s*\(1\))?\s+Tipo de Cambio\s+"
    r"([\d.,]+)\s+([A-Z]{3})\s+"
    r"([\d.,]+)\s+([A-Z]{3})\s+"
    r"([\d.,]+)\s+([A-Z]{3})\s+"
    r"([\d.,]+)\s+([A-Z]{3})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedMyInvestorTrade:
    side: str
    reference: str
    ticker: str
    isin: str
    market: str
    instrument_name: str
    transaction_date: date
    """Fecha Operación: día de negocio, usado para cortes de mes."""
    execution_datetime: datetime
    """Fecha y Hora Ejecución (valores cotizados) o fin del día de operación (fondos)."""
    asset_amount: Decimal
    gross_price: Decimal
    gross_amount: Decimal
    trade_currency: str
    fee_amount: Decimal
    net_trade_amount: Decimal
    settlement_amount: Decimal
    settlement_currency: str


@dataclass(frozen=True)
class TradeAmounts:
    invested_amount: Decimal
    asset_amount: Decimal
    execution_price: Decimal
    fee_amount: Decimal


@dataclass(frozen=True)
class _NetParsed:
    net_trade_amount: Decimal
    settlement_amount: Decimal
    settlement_currency: str


def looks_like_trade_confirmation(body: str) -> bool:
    folded = body.upper()
    return "CONFIRMACI" in folded and "OPERACI" in folded


def normalize_myinvestor_body(body: str) -> str:
    return body.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")


def parse_decimal_amount(raw: str) -> Decimal:
    """Acepta 441.00, 110.250 y el formato europeo 1.234,56."""
    text = raw.strip().replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    return Decimal(text)


def _parse_side(raw: str) -> str:
    upper = raw.upper()
    if upper.startswith("SUSCRIPCION"):
        return "SUSCRIPCION"
    return upper


def is_purchase_side(side: str) -> bool:
    return side in ("COMPRA", "SUSCRIPCION")


def _parse_instrument(text: str) -> tuple[str, str, str, str] | None:
    listed = _INSTRUMENT_LISTED_RE.search(text)
    if listed:
        return (
            listed.group("market").upper(),
            re.sub(r"\s+", " ", listed.group("name")).strip(),
            listed.group("ticker").upper(),
            listed.group("isin").upper(),
        )
    fund = _INSTRUMENT_FUND_RE.search(text)
    if fund:
        isin = fund.group("isin").upper()
        return (
            re.sub(r"\s+", " ", fund.group("market")).strip().upper(),
            re.sub(r"\s+", " ", fund.group("name")).strip(),
            isin,
            isin,
        )
    return None


def _parse_operation(text: str) -> tuple[str, str] | None:
    match = _OPERATION_RE.search(text)
    if not match:
        return None
    return _parse_side(match.group(1)), match.group(2)


def _parse_dates(text: str) -> tuple[date, datetime] | None:
    listed = _DATES_LISTED_RE.search(text)
    if listed:
        transaction_date = datetime.strptime(listed.group(1), "%d/%m/%Y").date()
        execution_datetime = datetime.strptime(
            f"{listed.group(3)} {listed.group(4)}", "%d/%m/%Y %H:%M:%S"
        )
        return transaction_date, execution_datetime

    fund = _DATES_FUND_RE.search(text)
    if fund:
        transaction_date = datetime.strptime(fund.group(1), "%d/%m/%Y").date()
        execution_datetime = datetime.combine(transaction_date, time(23, 59, 59))
        return transaction_date, execution_datetime

    return None


def _parse_net_block(text: str) -> _NetParsed | None:
    """Detecta neto según plantilla (fondos, FX cruzado o solo EUR)."""
    fund = _NET_FUND_RE.search(text)
    if fund:
        net = parse_decimal_amount(fund.group(5))
        currency = fund.group(6).upper()
        return _NetParsed(net, net, currency)

    fx = _NET_FX_RE.search(text)
    if fx:
        return _NetParsed(
            parse_decimal_amount(fx.group(5)),
            parse_decimal_amount(fx.group(7)),
            fx.group(8).upper(),
        )

    eur_only = _NET_EUR_ONLY_RE.search(text)
    if eur_only:
        net = parse_decimal_amount(eur_only.group(5))
        currency = eur_only.group(6).upper()
        return _NetParsed(net, net, currency)

    return None


def diagnose_myinvestor_parse(body: str) -> list[str]:
    """Motivos por los que `parse_myinvestor_trade` devolvería None (para depuración)."""
    if not looks_like_trade_confirmation(body):
        return ["no parece confirmación de operación (falta CONFIRMACIÓN/OPERACIÓN en el texto)"]

    text = normalize_myinvestor_body(body)
    missing: list[str] = []
    if _parse_instrument(text) is None:
        missing.append("bloque Mercado/Valor/ISIN (instrumento)")
    if _parse_operation(text) is None:
        missing.append("operación COMPRA|VENTA|SUSCRIPCION con referencia N/N")
    if _parse_dates(text) is None:
        missing.append("fechas (cotizados: Operación+Valor+Ejecución+hora; fondos: Operación+Valor)")
    amounts_match = _AMOUNTS_RE.search(text)
    if not amounts_match:
        missing.append("importes (títulos, precio bruto, importe bruto)")
    if not _FEES_RE.search(text):
        missing.append("comisiones/gastos/tasas")
    if _parse_net_block(text) is None:
        missing.append("importe efectivo neto")
    if missing:
        return missing

    assert amounts_match is not None
    price_currency = amounts_match.group(3).upper()
    gross_currency = amounts_match.group(5).upper()
    if price_currency != gross_currency:
        return [f"divisa precio ({price_currency}) distinta de divisa bruto ({gross_currency})"]

    fees = _FEES_RE.search(text)
    assert fees is not None
    for raw_amount, raw_currency, label in (
        (fees.group(1), fees.group(2), "comisión 1"),
        (fees.group(3), fees.group(4), "gasto"),
        (fees.group(5), fees.group(6), "tasa/impuesto"),
    ):
        if raw_currency.upper() != price_currency:
            return [f"{label} en {raw_currency.upper()}, distinta de {price_currency}"]

    asset_amount = parse_decimal_amount(amounts_match.group(1))
    if asset_amount <= 0:
        return ["número de títulos <= 0"]

    return []


def parse_myinvestor_trade(body: str) -> ParsedMyInvestorTrade | None:
    """Extrae una confirmación de compra, venta o suscripción a fondo."""
    if diagnose_myinvestor_parse(body):
        return None

    text = normalize_myinvestor_body(body)
    instrument = _parse_instrument(text)
    operation = _parse_operation(text)
    dates = _parse_dates(text)
    amounts = _AMOUNTS_RE.search(text)
    fees = _FEES_RE.search(text)
    net = _parse_net_block(text)
    assert instrument and operation and dates and amounts and fees and net

    market, instrument_name, ticker, isin = instrument
    side, reference = operation
    transaction_date, execution_datetime = dates

    price_currency = amounts.group(3).upper()
    gross_currency = amounts.group(5).upper()
    if price_currency != gross_currency:
        return None

    fee_parts: list[Decimal] = []
    for raw_amount, raw_currency in (
        (fees.group(1), fees.group(2)),
        (fees.group(3), fees.group(4)),
        (fees.group(5), fees.group(6)),
    ):
        if raw_currency.upper() != price_currency:
            return None
        fee_parts.append(parse_decimal_amount(raw_amount))

    asset_amount = parse_decimal_amount(amounts.group(1))
    if asset_amount <= 0:
        return None

    return ParsedMyInvestorTrade(
        side=side,
        reference=reference,
        ticker=ticker,
        isin=isin,
        market=market,
        instrument_name=instrument_name,
        transaction_date=transaction_date,
        execution_datetime=execution_datetime,
        asset_amount=asset_amount,
        gross_price=parse_decimal_amount(amounts.group(2)),
        gross_amount=parse_decimal_amount(amounts.group(4)),
        trade_currency=price_currency,
        fee_amount=sum(fee_parts, Decimal("0")),
        net_trade_amount=net.net_trade_amount,
        settlement_amount=net.settlement_amount,
        settlement_currency=net.settlement_currency,
    )


def amounts_for_asset_currency(trade: ParsedMyInvestorTrade, asset_currency: str) -> TradeAmounts | None:
    """Expresa coste, precio y comisión en la divisa de asset_types.

    Si la operación ya está en esa divisa, se usa el importe bruto.
    Si no, se aplica el tipo implícito del correo (neto en divisa de liquidación / neto de la operación).
    """
    currency = asset_currency.upper()
    if trade.trade_currency == currency:
        invested = trade.gross_amount
        fee = trade.fee_amount
        price = trade.gross_price
    elif trade.settlement_currency == currency and trade.net_trade_amount > 0:
        rate = trade.settlement_amount / trade.net_trade_amount
        invested = trade.gross_amount * rate
        fee = trade.fee_amount * rate
        price = invested / trade.asset_amount
    else:
        return None

    return TradeAmounts(
        invested_amount=_q(invested),
        asset_amount=trade.asset_amount,
        execution_price=_q(price),
        fee_amount=_q(fee),
    )


def _q(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT)
