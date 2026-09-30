"""Agregación del "libro mayor" de inversiones: entity_cash_flows + asset_transactions
agrupados por entidad financiera.

Dentro de cada entidad:
- Movimientos de caja arriba.
- Activos con transacciones: si hay más de una categoría, se agrupan por categoría
  (orden global de categorías + display_order del activo); si solo hay una, lista plana.
"""

from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset_transaction import AssetTransaction
from app.models.asset_type import AssetType
from app.models.entity import Entity
from app.models.entity_cash_flow import EntityCashFlow
from app.models.investment_category import InvestmentCategory
from app.schemas.ledger import (
    AssetLedgerGroup,
    AssetTransactionLedgerRow,
    CategoryLedgerGroup,
    EntityLedgerGroup,
    EntityCashFlowRow,
)


def _round2(value) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01")))


def _round8(value) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.00000001")))


def _build_asset_ledger_group(
    asset: AssetType, tx_by_asset: dict[UUID, list[tuple]]
) -> AssetLedgerGroup:
    running_amount = Decimal("0")
    running_units = Decimal("0")
    transactions: list[AssetTransactionLedgerRow] = []
    for transaction_date, invested_amount, asset_amount, execution_price in tx_by_asset.get(asset.id, []):
        invested = Decimal(str(invested_amount))
        price = Decimal(str(execution_price or 0))
        units = Decimal(str(asset_amount))
        running_amount += invested
        running_units += units
        avg_price = (running_amount / running_units) if running_units > 0 else Decimal("0")
        transactions.append(
            AssetTransactionLedgerRow(
                fecha=transaction_date,
                currency=asset.currency,
                precio_promedio=_round2(avg_price),
                precio_compra=_round2(price),
                euros_metidos=_round2(invested),
                euros_totales=_round2(running_amount),
                asset_comprado=_round8(units),
                asset_acumulado=_round8(running_units),
            )
        )
    last_tx = transactions[-1] if transactions else None
    return AssetLedgerGroup(
        asset_type_id=str(asset.id),
        exchange_ticker=asset.name,
        currency=asset.currency,
        total_asset_acumulado=last_tx.asset_acumulado if last_tx else 0,
        total_euros_metidos=last_tx.euros_totales if last_tx else 0,
        last_precio_compra=last_tx.precio_compra if last_tx else 0,
        transactions=transactions,
    )


def _sort_assets(assets: list[AssetType]) -> list[AssetType]:
    return sorted(assets, key=lambda a: (a.display_order, a.name))


def _entity_asset_payload(
    entity_assets: list[AssetType],
    tx_by_asset: dict[UUID, list[tuple]],
    categories_by_id: dict[str, InvestmentCategory],
    category_order: list[InvestmentCategory],
) -> tuple[list[AssetLedgerGroup], list[CategoryLedgerGroup]]:
    assets_by_category: dict[str, list[AssetType]] = defaultdict(list)
    for asset in entity_assets:
        assets_by_category[asset.category_id].append(asset)

    category_ids_present = {cat_id for cat_id, items in assets_by_category.items() if items}

    if len(category_ids_present) <= 1:
        flat = [_build_asset_ledger_group(asset, tx_by_asset) for asset in _sort_assets(entity_assets)]
        return flat, []

    asset_categories: list[CategoryLedgerGroup] = []
    for category in category_order:
        cat_assets = _sort_assets(assets_by_category.get(category.id, []))
        if not cat_assets:
            continue
        cat = categories_by_id.get(category.id, category)
        asset_categories.append(
            CategoryLedgerGroup(
                category_id=cat.id,
                category_name=cat.name,
                color=cat.color,
                assets=[_build_asset_ledger_group(asset, tx_by_asset) for asset in cat_assets],
            )
        )
    return [], asset_categories


def build_investment_ledger(db: Session) -> list[EntityLedgerGroup]:
    entities_by_id = {e.id: e for e in db.scalars(select(Entity)).all()}

    cash_flows_by_entity: dict[str, list[tuple]] = defaultdict(list)
    cash_flow_rows = db.execute(
        select(EntityCashFlow.entity_id, EntityCashFlow.amount, EntityCashFlow.flow_date)
        .where(EntityCashFlow.entity_id.is_not(None))
        .order_by(EntityCashFlow.flow_date.asc().nulls_last(), EntityCashFlow.id.asc())
    ).all()
    for entity_id, amount, flow_date in cash_flow_rows:
        cash_flows_by_entity[entity_id].append((amount, flow_date))

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

    asset_types = list(db.scalars(select(AssetType).where(AssetType.entity_id.is_not(None))).all())
    assets_by_entity: dict[str, list[AssetType]] = defaultdict(list)
    for asset in asset_types:
        if tx_by_asset.get(asset.id):
            assets_by_entity[asset.entity_id].append(asset)

    category_order = list(
        db.scalars(select(InvestmentCategory).order_by(InvestmentCategory.display_order)).all()
    )
    categories_by_id = {cat.id: cat for cat in category_order}

    entity_ids = set(cash_flows_by_entity) | set(assets_by_entity)

    groups: list[EntityLedgerGroup] = []
    for entity_id in entity_ids:
        entity = entities_by_id.get(entity_id)
        entity_name = entity.name if entity else entity_id

        entity_cash_flows: list[EntityCashFlowRow] = []
        running_total = Decimal("0")
        for amount, flow_date in cash_flows_by_entity.get(entity_id, []):
            running_total += Decimal(str(amount))
            entity_cash_flows.append(
                EntityCashFlowRow(
                    fecha=flow_date,
                    cantidad=_round2(amount),
                    total_acumulado=_round2(running_total),
                )
            )

        flat_assets, asset_categories = _entity_asset_payload(
            assets_by_entity.get(entity_id, []),
            tx_by_asset,
            categories_by_id,
            category_order,
        )

        groups.append(
            EntityLedgerGroup(
                entity_name=entity_name,
                entity_cash_flows=entity_cash_flows,
                assets=flat_assets,
                asset_categories=asset_categories,
            )
        )

    groups.sort(key=lambda g: g.entity_name)
    return groups
