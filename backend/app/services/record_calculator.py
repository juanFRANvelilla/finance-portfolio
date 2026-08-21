from decimal import Decimal

from app.models.entity import Entity, EntityType
from app.models.monthly_record import MonthlyRecord
from app.schemas.monthly_record import EntityBalanceInput, HybridBalanceImport, ImportPayload


def _round2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def compute_totals_from_record(record: MonthlyRecord) -> dict[str, float]:
    """Calcula totales al vuelo a partir de balances simples e híbridos del registro."""
    total_liquid = Decimal("0")
    total_invested = Decimal("0")

    for balance in record.balances:
        entity_type = balance.entity.entity_type if balance.entity else None
        amount = Decimal(str(balance.balance_amount))
        if entity_type == EntityType.LIQUID:
            total_liquid += amount
        elif entity_type == EntityType.INVESTED:
            total_invested += amount

    for hybrid in record.hybrid_accounts:
        total_liquid += Decimal(str(hybrid.liquid_amount))
        total_invested += Decimal(str(hybrid.cumulative_invested))

    total_net_worth = total_liquid + total_invested
    invested_percentage = (
        (total_invested / total_net_worth * Decimal("100")) if total_net_worth else Decimal("0")
    )

    return {
        "total_liquid": _round2(total_liquid),
        "total_invested": _round2(total_invested),
        "total_net_worth": _round2(total_net_worth),
        "invested_percentage": _round2(invested_percentage),
    }


def compute_totals_from_simple_balances(
    balances: list[EntityBalanceInput],
    entities_by_id: dict[str, Entity],
    hybrid_balances: list[HybridBalanceImport] | None = None,
) -> dict[str, float]:
    """Calcula totales a partir de balances simples y, opcionalmente, híbridos (formulario manual)."""
    total_liquid = Decimal("0")
    total_invested = Decimal("0")

    for balance in balances:
        entity = entities_by_id[balance.entity_id]
        amount = Decimal(str(balance.balance_amount))
        if entity.entity_type == EntityType.LIQUID:
            total_liquid += amount
        elif entity.entity_type == EntityType.INVESTED:
            total_invested += amount

    for hybrid in hybrid_balances or []:
        total_liquid += Decimal(str(hybrid.liquid_amount))
        total_invested += Decimal(str(hybrid.invested_amount))

    total_net_worth = total_liquid + total_invested
    invested_percentage = (
        (total_invested / total_net_worth * Decimal("100")) if total_net_worth else Decimal("0")
    )

    return {
        "total_liquid": _round2(total_liquid),
        "total_invested": _round2(total_invested),
        "total_net_worth": _round2(total_net_worth),
        "invested_percentage": _round2(invested_percentage),
    }


def compute_totals_from_import(payload: ImportPayload, entities_by_id: dict[str, Entity]) -> dict[str, float]:
    """Calcula totales al vuelo a partir del payload de importación."""
    total_liquid = Decimal("0")
    total_invested = Decimal("0")

    for balance in payload.simple_balances:
        entity = entities_by_id[balance.entity_id]
        amount = Decimal(str(balance.amount))
        if entity.entity_type == EntityType.LIQUID:
            total_liquid += amount
        elif entity.entity_type == EntityType.INVESTED:
            total_invested += amount

    for hybrid in payload.hybrid_balances:
        total_liquid += Decimal(str(hybrid.liquid_amount))
        total_invested += Decimal(str(hybrid.invested_amount))

    total_net_worth = total_liquid + total_invested
    invested_percentage = (
        (total_invested / total_net_worth * Decimal("100")) if total_net_worth else Decimal("0")
    )

    return {
        "total_liquid": _round2(total_liquid),
        "total_invested": _round2(total_invested),
        "total_net_worth": _round2(total_net_worth),
        "invested_percentage": _round2(invested_percentage),
    }
