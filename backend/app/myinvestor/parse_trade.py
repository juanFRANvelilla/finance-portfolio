"""Parser de confirmaciones de operación de valores de MyInvestor."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

MONEY_QUANT = Decimal("0.00000001")

_INSTRUMENT_RE = re.compile(
    r"Mercado\s+Valor\s+"
    r"(?P<market>[A-Z0-9]{2,})\s+"
    r"(?P<name>.+?)\s+-\s+"
    r"(?P<ticker>[A-Z0-9][A-Z0-9.]*)"
    r"(?:\s+[A-Z]{2})?"
    r"\s+C[oó]digo\s+ISIN:\s*"
    r"(?P<isin>[A-Z]{2}[A-Z0-9]{10})",
    re.IGNORECASE | re.DOTALL,
)
_OPERATION_RE = re.compile(r"\b(COMPRA|VENTA)\s+(\d+/\d+)\b", re.IGNORECASE)
_DATES_RE = re.compile(
    r"(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})"
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
_NET_RE = re.compile(
    r"Importe Efectivo Neto(?:\s*\(1\))?\s+"
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


def looks_like_trade_confirmation(body: str) -> bool:
    folded = body.upper()
    return "CONFIRMACI" in folded and "OPERACI" in folded


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


def parse_myinvestor_trade(body: str) -> ParsedMyInvestorTrade | None:
    """Extrae una confirmación de compra o venta. Devuelve None si el texto no encaja."""
    if not looks_like_trade_confirmation(body):
        return None

    text = body.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    instrument = _INSTRUMENT_RE.search(text)
    operation = _OPERATION_RE.search(text)
    dates = _DATES_RE.search(text)
    amounts = _AMOUNTS_RE.search(text)
    fees = _FEES_RE.search(text)
    net = _NET_RE.search(text)
    if not all((instrument, operation, dates, amounts, fees, net)):
        return None

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

    net_currency = net.group(6).upper()
    if net_currency != price_currency:
        return None

    asset_amount = parse_decimal_amount(amounts.group(1))
    if asset_amount <= 0:
        return None

    return ParsedMyInvestorTrade(
        side=operation.group(1).upper(),
        reference=operation.group(2),
        ticker=instrument.group("ticker").upper(),
        isin=instrument.group("isin").upper(),
        market=instrument.group("market").upper(),
        instrument_name=re.sub(r"\s+", " ", instrument.group("name")).strip(),
        transaction_date=datetime.strptime(dates.group(1), "%d/%m/%Y").date(),
        asset_amount=asset_amount,
        gross_price=parse_decimal_amount(amounts.group(2)),
        gross_amount=parse_decimal_amount(amounts.group(4)),
        trade_currency=price_currency,
        fee_amount=sum(fee_parts, Decimal("0")),
        net_trade_amount=parse_decimal_amount(net.group(5)),
        settlement_amount=parse_decimal_amount(net.group(7)),
        settlement_currency=net.group(8).upper(),
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
