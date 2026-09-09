"""Agregación del "libro mayor" de inversiones: fiat_deposits + asset_transactions
agrupados por entidad financiera, replicando el histórico completo (sin filtrar por mes).

Reglas clave:
- Solo se listan entidades que tengan al menos un depósito fiat o un activo con
  transacciones reales; nunca se inventan filas.
- Solo se listan activos (asset_types) que tengan >= 1 fila en asset_transactions.
  Un activo sin transacciones (p. ej. MSCI World sin operaciones registradas) no aparece.
- Todos los importes en asset_transactions ya están en EUR (ver
  register-legacy-crypto-trades.py: invested_amount / execution_price se calculan en EUR
  en el momento de la ingesta), así que aquí no se hace ninguna conversión de divisa.
"""

from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset_transaction import AssetTransaction
from app.models.asset_type import AssetType
from app.models.entity import Entity
from app.models.fiat_deposit import FiatDeposit
from app.schemas.ledger import AssetLedgerGroup, AssetTransactionLedgerRow, EntityLedgerGroup, FiatDepositRow


def _round2(value) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01")))


def _round8(value) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.00000001")))


def build_investment_ledger(db: Session) -> list[EntityLedgerGroup]:
    entities_by_id = {e.id: e for e in db.scalars(select(Entity)).all()}

    # ---- Depósitos fiat, agrupados por entidad y ordenados cronológicamente ----
    # Nota: se seleccionan columnas explícitas (no el modelo completo) porque
    # FiatDeposit.created_at está mapeado en el ORM pero no existe en la tabla real.
    deposits_by_entity: dict[str, list[tuple]] = defaultdict(list)
    deposit_rows = db.execute(
        select(FiatDeposit.entity_id, FiatDeposit.amount, FiatDeposit.deposit_date)
        .where(FiatDeposit.entity_id.is_not(None))
        .order_by(FiatDeposit.deposit_date.asc().nulls_last(), FiatDeposit.id.asc())
    ).all()
    for entity_id, amount, deposit_date in deposit_rows:
        deposits_by_entity[entity_id].append((amount, deposit_date))

    # ---- Transacciones, agrupadas por activo y ordenadas cronológicamente ----
    # Nota: mismo motivo que en fiat_deposits; AssetTransaction.created_at está
    # mapeado en el ORM pero no existe en la tabla real, así que evitamos select(AssetTransaction).
    tx_by_asset: dict[UUID, list[tuple]] = defaultdict(list)
    tx_rows = db.execute(
        select(
            AssetTransaction.asset_type_id,
            AssetTransaction.transaction_date,
            AssetTransaction.invested_amount,
            AssetTransaction.asset_amount,
            AssetTransaction.execution_price,
        ).order_by(AssetTransaction.transaction_date.asc().nulls_last(), AssetTransaction.id.asc())
    ).all()
    for asset_type_id, transaction_date, invested_amount, asset_amount, execution_price in tx_rows:
        tx_by_asset[asset_type_id].append((transaction_date, invested_amount, asset_amount, execution_price))

    # ---- Activos vinculados a una entidad que además tengan >= 1 transacción ----
    asset_types = db.scalars(select(AssetType).where(AssetType.entity_id.is_not(None))).all()
    assets_by_entity: dict[str, list[AssetType]] = defaultdict(list)
    for asset in asset_types:
        if tx_by_asset.get(asset.id):
            assets_by_entity[asset.entity_id].append(asset)

    entity_ids = set(deposits_by_entity) | set(assets_by_entity)

    groups: list[EntityLedgerGroup] = []
    for entity_id in entity_ids:
        entity = entities_by_id.get(entity_id)
        entity_name = entity.name if entity else entity_id

        fiat_deposits: list[FiatDepositRow] = []
        running_total = Decimal("0")
        for amount, deposit_date in deposits_by_entity.get(entity_id, []):
            running_total += Decimal(str(amount))
            fiat_deposits.append(
                FiatDepositRow(
                    fecha=deposit_date,
                    cantidad=_round2(amount),
                    total_acumulado=_round2(running_total),
                )
            )

        asset_groups: list[AssetLedgerGroup] = []
        for asset in sorted(assets_by_entity.get(entity_id, []), key=lambda a: a.display_order):
            running_eur = Decimal("0")
            running_units = Decimal("0")
            transactions: list[AssetTransactionLedgerRow] = []
            for transaction_date, invested_amount, asset_amount, execution_price in tx_by_asset.get(
                asset.id, []
            ):
                invested = Decimal(str(invested_amount))
                units = Decimal(str(asset_amount))
                running_eur += invested
                running_units += units
                avg_price = (running_eur / running_units) if running_units > 0 else Decimal("0")
                transactions.append(
                    AssetTransactionLedgerRow(
                        fecha=transaction_date,
                        precio_promedio=_round2(avg_price),
                        precio_compra=_round2(execution_price or 0),
                        euros_metidos=_round2(invested),
                        euros_totales=_round2(running_eur),
                        asset_comprado=_round8(units),
                        asset_acumulado=_round8(running_units),
                    )
                )
            asset_groups.append(
                AssetLedgerGroup(exchange_ticker=asset.ticker or asset.name, transactions=transactions)
            )

        groups.append(
            EntityLedgerGroup(entity_name=entity_name, fiat_deposits=fiat_deposits, assets=asset_groups)
        )

    groups.sort(key=lambda g: g.entity_name)
    return groups
