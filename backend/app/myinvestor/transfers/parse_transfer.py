"""Parser de correos de transferencia MyInvestor (TRANSFERENCIA INMEDIATA, etc.)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.myinvestor.trades.parse_trade import normalize_myinvestor_body, parse_decimal_amount

TRANSFER_SOURCE_PREFIX = "myinvestor:transfer:"

_REFERENCE_RE = re.compile(
    r"TRANSFERENCIA\s+INMEDIATA\s+(?P<ref>[a-f0-9]{32})\s+MYINVESTOR",
    re.IGNORECASE,
)
_OPERATION_DATES_RE = re.compile(
    r"Fecha\s+Operaci[oó]n\s+Fecha\s+Valor\s+"
    r"(?P<op_date>\d{2}/\d{2}/\d{4})\s+(?P<val_date>\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_NET_AMOUNT_RE = re.compile(
    r"Importe\s+Neto(?:\s*\(1\))?\s+"
    r"(?P<amount>[\d.,]+)\s+(?P<currency>[A-Z]{3})",
    re.IGNORECASE | re.DOTALL,
)
_SUBJECT_DATE_RE = re.compile(r"#Fecha:(?P<date>\d{2}-\d{2}-\d{4})#", re.IGNORECASE)
_SUBJECT_AMOUNT_RE = re.compile(r"#\s*([\d.,]+)\s*$")


@dataclass(frozen=True)
class ParsedMyInvestorTransfer:
    reference: str
    operation_label: str
    flow_date: date
    amount: Decimal
    """Importe con signo (+ entrada en MyInvestor, − salida)."""
    currency: str

    @property
    def source_reference(self) -> str:
        return f"{TRANSFER_SOURCE_PREFIX}{self.reference}"


def looks_like_transfer_mail(subject: str, body: str) -> bool:
    subj = (subject or "").upper()
    if "MYINVESTOR" in subj and "TRANSFERENCIA" in subj:
        return True
    text = normalize_myinvestor_body(body).upper()
    return "TRANSFERENCIA INMEDIATA" in text and "DETALLE OPERACI" in text


def _parse_date_dd_mm_yyyy(raw: str) -> date | None:
    try:
        return datetime.strptime(raw.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _parse_date_dd_mm_yyyy_dashes(raw: str) -> date | None:
    try:
        return datetime.strptime(raw.strip(), "%d-%m-%Y").date()
    except ValueError:
        return None


def diagnose_transfer_parse(subject: str, body: str) -> list[str]:
    reasons: list[str] = []
    if not looks_like_transfer_mail(subject, body):
        reasons.append("no_parece_transferencia_myinvestor")
        return reasons

    text = normalize_myinvestor_body(body)
    if not _REFERENCE_RE.search(text):
        reasons.append("sin_referencia_operacion")
    if not _OPERATION_DATES_RE.search(text) and not _SUBJECT_DATE_RE.search(subject or ""):
        reasons.append("sin_fecha_operacion")
    if not _NET_AMOUNT_RE.search(text) and not _SUBJECT_AMOUNT_RE.search(subject or ""):
        reasons.append("sin_importe_neto")
    return reasons


def parse_myinvestor_transfer(subject: str, body: str) -> ParsedMyInvestorTransfer | None:
    if diagnose_transfer_parse(subject, body):
        return None

    text = normalize_myinvestor_body(body)
    ref_match = _REFERENCE_RE.search(text)
    if not ref_match:
        return None
    reference = ref_match.group("ref").lower()

    flow_date: date | None = None
    dates_match = _OPERATION_DATES_RE.search(text)
    if dates_match:
        flow_date = _parse_date_dd_mm_yyyy(dates_match.group("op_date"))
    if flow_date is None:
        subj_date = _SUBJECT_DATE_RE.search(subject or "")
        if subj_date:
            flow_date = _parse_date_dd_mm_yyyy_dashes(subj_date.group("date"))
    if flow_date is None:
        return None

    currency = "EUR"
    amount_raw: str | None = None
    net_match = _NET_AMOUNT_RE.search(text)
    if net_match:
        amount_raw = net_match.group("amount")
        currency = net_match.group("currency").upper()
    else:
        subj_amt = _SUBJECT_AMOUNT_RE.search(subject or "")
        if subj_amt:
            amount_raw = subj_amt.group(1)

    if amount_raw is None:
        return None

    amount_abs = parse_decimal_amount(amount_raw)
    # Entrada en la cuenta MyInvestor (plantilla actual TRANSFERENCIA INMEDIATA recibida).
    signed_amount = amount_abs

    return ParsedMyInvestorTransfer(
        reference=reference,
        operation_label="TRANSFERENCIA INMEDIATA",
        flow_date=flow_date,
        amount=signed_amount,
        currency=currency,
    )
