"""Ledger: ventas con invested_amount NULL restan coste vía PMP acumulado."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.models.asset_type import AssetType
from app.schemas.ledger import AssetLedgerGroup
from app.services.ledger import _build_asset_ledger_group


class LedgerSellNullInvestedTest(unittest.TestCase):
    def test_sell_with_null_invested_keeps_pmp_and_reduces_cost(self) -> None:
        asset_id = uuid4()
        asset = AssetType(
            id=asset_id,
            name="BTC",
            currency="EUR",
            entity_id="kucoin",
            category_id="crypto",
            display_order=0,
        )
        tx_by_asset = {
            asset_id: [
                (date(2026, 1, 1), Decimal("1000"), Decimal("1"), Decimal("1000")),
                (date(2026, 2, 1), None, Decimal("-0.5"), Decimal("1200")),
            ],
        }

        group: AssetLedgerGroup = _build_asset_ledger_group(asset, tx_by_asset)
        self.assertEqual(len(group.transactions), 2)
        buy, sell = group.transactions

        self.assertEqual(buy.euros_totales, 1000.0)
        self.assertEqual(buy.precio_promedio, 1000.0)

        self.assertEqual(sell.euros_metidos, -500.0)
        self.assertEqual(sell.euros_totales, 500.0)
        self.assertEqual(sell.asset_acumulado, 0.5)
        self.assertEqual(sell.precio_promedio, 1000.0)


if __name__ == "__main__":
    unittest.main()
