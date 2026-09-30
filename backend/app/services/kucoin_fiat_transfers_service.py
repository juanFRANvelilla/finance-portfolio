"""Consulta depósitos/retiros fiat EUR en KuCoin (ledger + API de retiros).

Los ingresos bancarios SEPA en KuCoin suelen aparecer en el ledger de cuenta
(`bizType=Fiat Deposit`, cuenta MAIN), no en GET /api/v1/deposits.
Este módulo no escribe en base de datos.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from collections.abc import Callable
from typing import Literal

import ccxt

from app.services.kucoin_sync_service import _kucoin_credentials

logger = logging.getLogger(__name__)

FIAT_CURRENCY = "EUR"
MAIN_ACCOUNT_TYPE = "MAIN"
LEDGER_BIZ_FIAT_DEPOSIT = "Fiat Deposit"
LEDGER_MAX_RANGE = timedelta(days=1)
PAGE_SIZE = 50
PAGE_SLEEP_SECONDS = 0.3
DAY_SLEEP_SECONDS = 0.05

ProgressCallback = Callable[[datetime, int, int, int], None]

KucoinFiatDirection = Literal["deposit", "withdrawal"]


@dataclass(frozen=True)
class KucoinFiatTransfer:
    direction: KucoinFiatDirection
    transfer_id: str
    currency: str
    amount: float
    fee: float
    status: str
    created_at: datetime
    address: str | None
    remark: str | None
    source: str
    raw: dict


@dataclass
class KucoinFiatTransfersResult:
    start_date: datetime
    end_date: datetime
    currency: str
    deposits_count: int = 0
    withdrawals_count: int = 0
    transfers: list[KucoinFiatTransfer] = field(default_factory=list)
    success: bool = True
    error: str | None = None
    messages: list[str] = field(default_factory=list)


def fetch_kucoin_eur_fiat_transfers(
    start_date: datetime,
    end_date: datetime | None = None,
    *,
    currency: str = FIAT_CURRENCY,
    on_progress: ProgressCallback | None = None,
) -> KucoinFiatTransfersResult:
    """Lista depósitos/retiros fiat EUR entre fechas (solo lectura API)."""
    end = end_date or datetime.now()
    result = KucoinFiatTransfersResult(
        start_date=start_date,
        end_date=end,
        currency=currency.upper(),
    )

    if start_date >= end:
        result.success = False
        result.error = "start_date debe ser anterior a end_date."
        return result

    try:
        exchange = _create_kucoin_exchange()
        currency_code = result.currency

        deposits_raw = _fetch_fiat_deposits_from_ledgers(
            exchange,
            start_date=start_date,
            end_date=end,
            currency=currency_code,
            on_progress=on_progress,
        )
        withdrawals_raw = _fetch_fiat_withdrawals_from_api(
            exchange,
            start_date=start_date,
            end_date=end,
            currency=currency_code,
            on_progress=on_progress,
        )

        seen_ids: set[str] = set()
        for item in deposits_raw:
            parsed = _parse_ledger_fiat_deposit(item, expected_currency=currency_code)
            if parsed is not None and parsed.transfer_id not in seen_ids:
                seen_ids.add(parsed.transfer_id)
                result.transfers.append(parsed)

        for item in withdrawals_raw:
            parsed = _parse_api_withdrawal(item, expected_currency=currency_code)
            if parsed is not None and parsed.transfer_id not in seen_ids:
                seen_ids.add(parsed.transfer_id)
                result.transfers.append(parsed)

        result.deposits_count = sum(1 for t in result.transfers if t.direction == "deposit")
        result.withdrawals_count = sum(1 for t in result.transfers if t.direction == "withdrawal")
        result.transfers.sort(key=lambda t: t.created_at)

        logger.info(
            "KuCoin fiat %s: %s depósitos, %s retiros (%s → %s)",
            currency_code,
            result.deposits_count,
            result.withdrawals_count,
            start_date.date(),
            end.date(),
        )
        if not result.transfers:
            result.messages.append(
                f"No hay depósitos/retiros fiat {currency_code} en el rango "
                f"{start_date.date()} → {end.date()}."
            )
        return result

    except Exception as exc:
        result.success = False
        result.error = str(exc)
        logger.exception("KuCoin fiat transfers falló: %s", exc)
        return result


def _create_kucoin_exchange() -> ccxt.kucoin:
    api_key, secret, passphrase = _kucoin_credentials()
    return ccxt.kucoin(
        {
            "apiKey": api_key,
            "secret": secret,
            "password": passphrase,
            "enableRateLimit": True,
            "timeout": 10_000,
        }
    )


def _fetch_fiat_deposits_from_ledgers(
    exchange: ccxt.kucoin,
    *,
    start_date: datetime,
    end_date: datetime,
    currency: str,
    on_progress: ProgressCallback | None = None,
) -> list[dict]:
    """Ledger MAIN: entradas `Fiat Deposit` (máx. 1 día por petición)."""
    return _scan_account_ledgers(
        exchange,
        start_date=start_date,
        end_date=end_date,
        currency=currency,
        on_progress=on_progress,
        predicate=lambda item: (
            item.get("accountType") == MAIN_ACCOUNT_TYPE
            and item.get("bizType") == LEDGER_BIZ_FIAT_DEPOSIT
            and item.get("direction") == "in"
        ),
    )


def _scan_account_ledgers(
    exchange: ccxt.kucoin,
    *,
    start_date: datetime,
    end_date: datetime,
    currency: str,
    predicate: Callable[[dict], bool],
    on_progress: ProgressCallback | None = None,
) -> list[dict]:
    collected: list[dict] = []
    day_start = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    if day_start < start_date:
        day_start = start_date

    total_days = max(1, (end_date.date() - day_start.date()).days + 1)
    day_index = 0

    logger.info(
        "KuCoin ledger %s: escaneo %s → %s",
        currency,
        start_date.date(),
        end_date.date(),
    )

    while day_start < end_date:
        day_index += 1
        day_end = min(day_start + LEDGER_MAX_RANGE, end_date)
        start_ms = int(day_start.timestamp() * 1000)
        end_ms = int(day_end.timestamp() * 1000)

        page = 1
        while True:
            response = exchange.private_get_accounts_ledgers(
                {
                    "currency": currency,
                    "startAt": start_ms,
                    "endAt": end_ms,
                    "pageSize": PAGE_SIZE,
                    "currentPage": page,
                }
            )
            data = response.get("data") or {}
            items = data.get("items") or []
            for item in items:
                if predicate(item):
                    collected.append(item)

            total_page = int(data.get("totalPage") or 1)
            if page >= total_page:
                break
            page += 1
            time.sleep(PAGE_SLEEP_SECONDS)

        if on_progress is not None:
            on_progress(day_start, day_index, total_days, len(collected))

        day_start = day_end
        time.sleep(DAY_SLEEP_SECONDS)

    return collected


def _fetch_fiat_withdrawals_from_api(
    exchange: ccxt.kucoin,
    *,
    start_date: datetime,
    end_date: datetime,
    currency: str,
    on_progress: ProgressCallback | None = None,
) -> list[dict]:
    """Retiros fiat vía GET /withdrawals (si KuCoin los expone para EUR)."""
    collected: list[dict] = []
    window_start = start_date
    total_span_days = max(1, (end_date.date() - start_date.date()).days + 1)

    while window_start < end_date:
        window_end = min(window_start + timedelta(days=30), end_date)
        start_ms = int(window_start.timestamp() * 1000)
        end_ms = int(window_end.timestamp() * 1000)

        page = 1
        while True:
            response = exchange.private_get_withdrawals(
                {
                    "currency": currency,
                    "currencyType": 1,
                    "startAt": start_ms,
                    "endAt": end_ms,
                    "pageSize": PAGE_SIZE,
                    "currentPage": page,
                }
            )
            data = response.get("data") or {}
            items = data.get("items") or []
            for item in items:
                if (item.get("currency") or "").upper() == currency.upper():
                    collected.append(item)

            total_page = int(data.get("totalPage") or 1)
            if page >= total_page:
                break
            page += 1
            time.sleep(PAGE_SLEEP_SECONDS)

        if on_progress is not None:
            done_days = min(
                total_span_days,
                max(1, (window_end.date() - start_date.date()).days + 1),
            )
            on_progress(window_end, done_days, total_span_days, len(collected))

        window_start = window_end + timedelta(seconds=1)
        time.sleep(DAY_SLEEP_SECONDS)

    return collected


def _parse_ledger_fiat_deposit(item: dict, *, expected_currency: str) -> KucoinFiatTransfer | None:
    currency = (item.get("currency") or "").upper()
    if currency != expected_currency.upper():
        return None

    created_ms = item.get("createdAt")
    if created_ms is None:
        return None

    try:
        amount = float(item.get("amount") or 0)
        fee = float(item.get("fee") or 0)
    except (TypeError, ValueError):
        return None

    transfer_id = str(item.get("id") or "")
    context_raw = item.get("context") or ""
    if context_raw:
        try:
            context = json.loads(context_raw)
            transfer_id = str(
                context.get("fiatDepositId") or context.get("paymentTxId") or transfer_id
            )
        except json.JSONDecodeError:
            pass

    if not transfer_id:
        transfer_id = f"ledger-deposit:{currency}:{created_ms}"

    return KucoinFiatTransfer(
        direction="deposit",
        transfer_id=transfer_id,
        currency=currency,
        amount=amount,
        fee=fee,
        status="SUCCESS",
        created_at=datetime.fromtimestamp(int(created_ms) / 1000, tz=UTC).replace(tzinfo=None),
        address=None,
        remark=None,
        source="accounts/ledgers",
        raw=item,
    )


def _parse_api_withdrawal(item: dict, *, expected_currency: str) -> KucoinFiatTransfer | None:
    currency = (item.get("currency") or "").upper()
    if currency != expected_currency.upper():
        return None

    created_ms = item.get("createdAt") or item.get("createAt")
    if created_ms is None:
        return None

    if isinstance(created_ms, str):
        try:
            created_ms = int(float(created_ms))
        except ValueError:
            return None

    if created_ms < 1_000_000_000_000:
        created_ms *= 1000

    try:
        amount = float(item.get("amount") or 0)
        fee = float(item.get("fee") or 0)
    except (TypeError, ValueError):
        return None

    transfer_id = str(item.get("id") or item.get("walletTxId") or f"withdraw:{created_ms}")

    return KucoinFiatTransfer(
        direction="withdrawal",
        transfer_id=transfer_id,
        currency=currency,
        amount=amount,
        fee=fee,
        status=str(item.get("status") or ""),
        created_at=datetime.fromtimestamp(created_ms / 1000, tz=UTC).replace(tzinfo=None),
        address=item.get("address"),
        remark=item.get("remark"),
        source="withdrawals",
        raw=item,
    )
