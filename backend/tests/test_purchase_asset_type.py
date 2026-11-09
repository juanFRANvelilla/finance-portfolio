"""Alta automática de un activo cuando una compra trae un ticker nuevo."""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models.asset_type import AssetType
from app.models.entity import Entity, EntityType
from app.models.investment_category import InvestmentCategory
from app.models.monthly_asset_investment import MonthlyAssetInvestment
from app.models.monthly_entity_position import MonthlyEntityPosition
from app.myinvestor.trades.parse_trade import parse_myinvestor_trade
from app.services import hybrid_entity_auto_adjust
from app.services.hybrid_entity_auto_adjust import apply_auto_trades_to_hybrid_entities
from app.services.purchase_asset_type import (
    create_myinvestor_asset_for_purchase,
    ensure_kucoin_purchase_assets,
)
from tests.test_myinvestor_parse import SAMPLE, SAMPLE_GOLD_EUR


class PurchaseAssetTypeTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite://")
        tables = [
            InvestmentCategory.__table__,
            Entity.__table__,
            AssetType.__table__,
            MonthlyAssetInvestment.__table__,
            MonthlyEntityPosition.__table__,
        ]
        for table in tables:
            table.create(engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add_all(
            [
                InvestmentCategory(id="stocks", name="Acciones", display_order=1),
                InvestmentCategory(id="crypto", name="Crypto", display_order=2),
                InvestmentCategory(id="fondos", name="Fondos", display_order=3),
                Entity(id="myinvestor", name="MyInvestor", entity_type=EntityType.HYBRID),
                Entity(id="kucoin", name="KuCoin", entity_type=EntityType.HYBRID),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def test_compra_myinvestor_crea_ticker_con_divisa_de_pago(self) -> None:
        trade = parse_myinvestor_trade(SAMPLE)
        assert trade is not None

        asset, created = create_myinvestor_asset_for_purchase(self.db, trade)
        self.db.commit()

        self.assertTrue(created)
        assert asset is not None
        self.assertEqual(asset.ticker, "BABA")
        self.assertEqual(asset.currency, "EUR")
        self.assertEqual(asset.entity_id, "myinvestor")
        self.assertEqual(asset.category_id, "stocks")
        self.assertEqual(asset.price_source, "yahoo")
        self.assertIn("ALIBABA", asset.name)

        again, created_again = create_myinvestor_asset_for_purchase(self.db, trade)
        self.assertFalse(created_again)
        assert again is not None
        self.assertEqual(again.id, asset.id)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(AssetType)), 1)

    def test_compra_nueva_baja_el_liquido_de_la_entidad(self) -> None:
        trade = parse_myinvestor_trade(SAMPLE_GOLD_EUR)
        assert trade is not None
        asset, created = create_myinvestor_asset_for_purchase(self.db, trade)
        self.assertTrue(created)
        assert asset is not None

        today = datetime.now()
        self.db.add(
            MonthlyEntityPosition(
                year=today.year,
                month=today.month,
                entity_id="myinvestor",
                liquid_amount=1000,
                invested_amount=0,
                created_at=today,
            )
        )
        self.db.add(
            MonthlyAssetInvestment(
                year=today.year,
                month=today.month,
                asset_type_id=asset.id,
                amount=Decimal("434.65"),
                units=Decimal("3"),
                last_update=today,
            )
        )
        self.db.commit()

        fill = {
            "exchange_trade_id": f"myinvestor:{trade.reference}",
            "asset_type_id": str(asset.id),
            "transaction_date": trade.transaction_date,
            "executed_at": today,
            "invested_amount": Decimal("434.65"),
            "asset_amount": Decimal("3"),
            "execution_price": Decimal("144.88333333"),
            "fee_amount": Decimal("1.00"),
        }
        # Postgres acepta el id en texto. SQLite no, así que la lectura del activo se adapta aquí.
        original_get = self.db.get

        def get_compat(model, ident, *args, **kwargs):
            if model is AssetType and isinstance(ident, str):
                ident = uuid.UUID(ident)
            return original_get(model, ident, *args, **kwargs)

        self.db.get = get_compat
        original_exists = hybrid_entity_auto_adjust._monthly_asset_row_exists
        hybrid_entity_auto_adjust._monthly_asset_row_exists = lambda *args, **kwargs: True
        try:
            result = apply_auto_trades_to_hybrid_entities(self.db, [fill], source="myinvestor")
        finally:
            hybrid_entity_auto_adjust._monthly_asset_row_exists = original_exists

        self.assertEqual(result.fills_liquid_adjusted, 1)
        self.assertEqual(result.fills_skipped, 0)
        position = self.db.scalars(select(MonthlyEntityPosition)).one()
        self.assertEqual(Decimal(str(position.liquid_amount)), Decimal("565.35"))
        monthly = self.db.scalars(select(MonthlyAssetInvestment)).one()
        self.assertEqual(Decimal(str(monthly.amount)), Decimal("434.65"))
        self.assertEqual(Decimal(str(position.invested_amount)), Decimal("434.65"))

    def test_compra_kucoin_crea_el_activo_y_no_repite(self) -> None:
        raw = [
            {"symbol": "SOL-USDT", "side": "buy", "tradeId": "1"},
            {"symbol": "SOL-EUR", "side": "buy", "tradeId": "2"},
            {"symbol": "ADA-EUR", "side": "sell", "tradeId": "3"},
        ]
        asset_map: dict[str, str] = {}
        created = ensure_kucoin_purchase_assets(self.db, raw, asset_map)
        self.db.commit()

        self.assertEqual(created, 1)
        self.assertIn("SOL", asset_map)
        self.assertNotIn("ADA", asset_map)
        sol = self.db.scalars(select(AssetType).where(AssetType.name == "SOL")).one()
        self.assertEqual(sol.ticker, "SOL-EUR")
        self.assertEqual(sol.currency, "EUR")
        self.assertEqual(sol.entity_id, "kucoin")
        self.assertEqual(sol.category_id, "crypto")
        self.assertEqual(sol.price_source, "kucoin")

        created_again = ensure_kucoin_purchase_assets(self.db, raw, {})
        self.assertEqual(created_again, 0)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(AssetType)), 1)


if __name__ == "__main__":
    unittest.main()
