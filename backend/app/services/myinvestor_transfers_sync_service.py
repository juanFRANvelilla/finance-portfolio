"""Sincronización IMAP MyInvestor/Transferencias → entity_cash_flows."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.myinvestor.mail import fetch_mailbox_messages
from app.myinvestor.transfers.parse_transfer import (
    diagnose_transfer_parse,
    looks_like_transfer_mail,
    parse_myinvestor_transfer,
)
from app.repositories.entity_cash_flows import insert_cash_flows_batch

logger = logging.getLogger(__name__)


@dataclass
class MyInvestorTransfersSyncResult:
    raw_emails_count: int = 0
    candidates: int = 0
    inserted: int = 0
    skipped_duplicate: int = 0
    skipped_unparsed: int = 0
    skipped_not_transfer: int = 0
    skipped_non_eur: int = 0
    success: bool = True
    error: str | None = None
    messages: list[str] = field(default_factory=list)


def _round2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def sync_myinvestor_transfers(
    *,
    dump_unparsed_bodies: bool = False,
) -> MyInvestorTransfersSyncResult:
    result = MyInvestorTransfersSyncResult()
    settings = get_settings()

    if not settings.imap_user or not settings.imap_password:
        result.success = False
        result.error = "Faltan credenciales IMAP. Define IMAP_USER e IMAP_PASSWORD."
        return result

    mailbox = settings.imap_mailbox_transfers
    entity_id = settings.myinvestor_entity_id

    try:
        messages = fetch_mailbox_messages(
            host=settings.imap_host,
            port=settings.imap_port,
            user=settings.imap_user,
            password=settings.imap_password,
            mailbox=mailbox,
        )
        result.raw_emails_count = len(messages)
        if not messages:
            result.messages.append(f"No hay correos en {mailbox!r}.")
            return result

        rows_to_insert: list[dict] = []

        for message in messages:
            if not looks_like_transfer_mail(message.subject, message.body):
                result.skipped_not_transfer += 1
                continue

            result.candidates += 1
            transfer = parse_myinvestor_transfer(message.subject, message.body)
            if transfer is None:
                result.skipped_unparsed += 1
                reasons = diagnose_transfer_parse(message.subject, message.body)
                logger.warning(
                    "Transferencia no parseada (UID=%s, asunto=%r): %s",
                    message.uid,
                    message.subject,
                    ", ".join(reasons) or "desconocido",
                )
                if dump_unparsed_bodies:
                    result.messages.append(
                        f"--- UID={message.uid} no parseado ({reasons}) ---\n{message.body}\n---"
                    )
                continue

            if transfer.currency != "EUR":
                result.skipped_non_eur += 1
                result.messages.append(
                    f"UID={message.uid} omitido: divisa {transfer.currency} (solo EUR por ahora)."
                )
                continue

            rows_to_insert.append(
                {
                    "entity_id": entity_id,
                    "amount": _round2(transfer.amount),
                    "flow_date": transfer.flow_date,
                    "source_reference": transfer.source_reference,
                }
            )
            result.messages.append(
                f"OK parse UID={message.uid} ref={transfer.reference} "
                f"fecha={transfer.flow_date} amount={_round2(transfer.amount)} EUR"
            )

        if rows_to_insert:
            with SessionLocal() as db:
                inserted, duplicates = insert_cash_flows_batch(db, rows_to_insert)
                db.commit()
                result.inserted = inserted
                result.skipped_duplicate = duplicates

        logger.info(
            "MyInvestor transfers sync: %s insertados, %s duplicados (%s correos)",
            result.inserted,
            result.skipped_duplicate,
            result.raw_emails_count,
        )
    except Exception as exc:
        result.success = False
        result.error = str(exc)
        logger.exception("MyInvestor transfers sync falló: %s", exc)

    return result


def run_scheduled_myinvestor_transfers_sync() -> MyInvestorTransfersSyncResult:
    """Sync IMAP de transferencias hacia entity_cash_flows (idempotencia por source_reference)."""
    logger.info("Sync MyInvestor transferencias: etiqueta %s", get_settings().imap_mailbox_transfers)
    return sync_myinvestor_transfers(dump_unparsed_bodies=False)
