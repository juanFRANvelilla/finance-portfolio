"""Importación del CSV de Trade Republic: solo TRADING buy/sell."""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models.asset_transaction import AssetTransaction
from app.models.asset_type import AssetType
from app.models.entity import Entity, EntityType
from app.models.investment_category import InvestmentCategory
from app.models.monthly_asset_investment import MonthlyAssetInvestment
from app.models.monthly_entity_position import MonthlyEntityPosition
from app.services import hybrid_entity_auto_adjust
from app.services.hybrid_entity_auto_adjust import apply_auto_trades_to_hybrid_entities
from app.services.trade_republic_csv_service import (
    TRADE_ID_PREFIX,
    TradeRepublicImportResult,
    _plan_fills,
    parse_trade_republic_csv,
)

CSV = """datetime,date,account_type,category,type,asset_class,name,symbol,shares,price,amount,fee,tax,currency,transaction_id
2026-08-10T06:47:56Z,2026-08-10,DEFAULT,CASH,TRANSFER_INBOUND,,,Juan,,"", "",1390,,"",EUR,cash-1
2026-08-14T13:46:56Z,2026-08-14,DEFAULT,TRADING,BUY,STOCK,Xiaomi,KYG9830T1067,185,2.8495,-527.16,-1,,EUR,buy-xiaomi
2026-11-01T10:00:00Z,2026-11-01,DEFAULT,TRADING,SELL,STOCK,NVIDIA,US67066G1040,-1,100,100,-1,,EUR,sell-nvidia-antes
2026-11-06T06:33:18Z,2026-11-06,DEFAULT,TRADING,SELL,STOCK,Xiaomi,KYG9830T1067,-185,3.4905,645.74,-1,,EUR,sell-xiaomi
2026-11-09T15:28:31Z,2026-11-09,DEFAULT,TRADING,BUY,STOCK,NVIDIA,US67066G1040,6,160,-960,-1,,EUR,buy-nvidia
2026-11-09T16:00:00Z,2026-11-09,DEFAULT,TRADING,BUY,STOCK,Apple,US0378331005,1,100,-100,-1,,USD,buy-apple
"""


class TradeRepublicCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite://")
        for table in (
            InvestmentCategory.__table__,
            Entity.__table__,
            AssetType.__table__,
            AssetTransaction.__table__,
            MonthlyAssetInvestment.__table__,
            MonthlyEntityPosition.__table__,
        ):
            table.create(engine)
        self.db = sessionmaker(bind=engine)()
        self.entity_id = get_settings().trade_republic_entity_id
        self.db.add_all(
            [
                InvestmentCategory(id="fondos", name="Fondos", display_order=1),
                InvestmentCategory(id="acciones", name="Acciones", display_order=2),
                Entity(id=self.entity_id, name="Trade Republic", entity_type=EntityType.HYBRID),
                Entity(id="myinvestor", name="MyInvestor", entity_type=EntityType.HYBRID),
                AssetType(
                    category_id="acciones",
                    name="NVIDIA",
                    ticker="US67066G1040",
                    currency="EUR",
                    entity_id="myinvestor",
                    display_order=1,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def test_compra_crea_activo_de_trade_republic_y_la_venta_ajusta_el_liquido(self) -> None:
        trades, parsed = parse_trade_republic_csv(CSV)
        self.assertTrue(parsed.success)
        self.assertEqual(parsed.trading_rows, 5)
        self.assertEqual([trade.transaction_id for trade in trades], [
            "buy-xiaomi",
            "sell-nvidia-antes",
            "sell-xiaomi",
            "buy-nvidia",
            "buy-apple",
        ])

        result = TradeRepublicImportResult()
        with self.assertLogs("app.services.trade_republic_csv_service", level="INFO") as captured:
            fills = _plan_fills(self.db, trades, result, self.entity_id, set(), {})
        self.db.commit()
        logged = "\n".join(captured.output)
        self.assertIn("Compra Trade Republic Xiaomi (KYG9830T1067, EUR): se crea el asset type", logged)
        self.assertIn("Compra Trade Republic NVIDIA (US67066G1040, EUR): se crea el asset type", logged)
        self.assertIn(
            "No se ha podido procesar la SELL NVIDIA (US67066G1040, 2026-11-01, ref sell-nvidia-antes)",
            logged,
        )
        self.assertIn("Trade Republic BUY Xiaomi (KYG9830T1067) 2026-08-14", logged)
        self.assertIn("Trade Republic SELL Xiaomi (KYG9830T1067) 2026-11-06", logged)
        self.assertNotIn("TRANSFER", logged)

        self.assertEqual(result.assets_created, 3)
        self.assertEqual(result.skipped_sell_without_asset, 1)
        self.assertEqual(len(fills), 4)

        xiaomi = self.db.scalars(select(AssetType).where(AssetType.name == "Xiaomi")).one()
        self.assertEqual(xiaomi.ticker, "KYG9830T1067")
        self.assertEqual(xiaomi.currency, "EUR")
        self.assertEqual(xiaomi.entity_id, self.entity_id)
        self.assertEqual(xiaomi.category_id, "acciones")
        self.assertEqual(xiaomi.price_source, "yahoo")

        nvidias = list(self.db.scalars(select(AssetType).where(AssetType.name == "NVIDIA")).all())
        self.assertEqual(len(nvidias), 2)
        created_nvidia = next(asset for asset in nvidias if asset.entity_id == self.entity_id)
        self.assertEqual(created_nvidia.ticker, "US67066G1040")
        self.assertEqual(created_nvidia.currency, "EUR")
        self.assertEqual(created_nvidia.price_source, "yahoo")

        apple = self.db.scalars(select(AssetType).where(AssetType.name == "Apple")).one()
        self.assertEqual(apple.currency, "USD")
        self.assertEqual(apple.entity_id, self.entity_id)

        buy = next(fill for fill in fills if fill["exchange_trade_id"] == f"{TRADE_ID_PREFIX}buy-xiaomi")
        sell = next(fill for fill in fills if fill["exchange_trade_id"] == f"{TRADE_ID_PREFIX}sell-xiaomi")
        self.assertEqual(buy["invested_amount"], Decimal("528.16000000"))
        self.assertEqual(buy["asset_amount"], Decimal("185.00000000"))
        self.assertEqual(sell["asset_amount"], Decimal("-185.00000000"))
        self.assertEqual(sell["net_liquidity"], Decimal("644.74000000"))
        self.assertLess(sell["invested_amount"], 0)
        self.assertNotIn(f"{TRADE_ID_PREFIX}sell-nvidia-antes", {fill["exchange_trade_id"] for fill in fills})

        today = datetime.now()
        self.db.add(
            MonthlyEntityPosition(
                year=today.year,
                month=today.month,
                entity_id=self.entity_id,
                liquid_amount=1000,
                invested_amount=0,
                created_at=today,
            )
        )
        self.db.add(
            MonthlyAssetInvestment(
                year=today.year,
                month=today.month,
                asset_type_id=xiaomi.id,
                amount=Decimal("528.16"),
                units=Decimal("185"),
                last_update=today,
            )
        )
        self.db.commit()

        original_get = self.db.get

        def get_compat(model, ident, *args, **kwargs):
            if model is AssetType and isinstance(ident, str):
                ident = uuid.UUID(ident)
            return original_get(model, ident, *args, **kwargs)

        self.db.get = get_compat
        original_exists = hybrid_entity_auto_adjust._monthly_asset_row_exists
        hybrid_entity_auto_adjust._monthly_asset_row_exists = lambda *args, **kwargs: True
        try:
            adjusted = apply_auto_trades_to_hybrid_entities(
                self.db,
                [{**buy, "executed_at": today}],
                source="trade_republic",
            )
        finally:
            hybrid_entity_auto_adjust._monthly_asset_row_exists = original_exists

        self.assertEqual(adjusted.fills_liquid_adjusted, 1)
        position = self.db.scalars(
            select(MonthlyEntityPosition).where(MonthlyEntityPosition.entity_id == self.entity_id)
        ).one()
        self.assertEqual(Decimal(str(position.liquid_amount)), Decimal("471.84"))

    def test_mismo_dia_y_mismo_tipo_se_omite_y_el_tipo_distinto_entra(self) -> None:
        xiaomi = AssetType(
            category_id="acciones",
            name="Xiaomi",
            ticker="3CP.HA",
            currency="EUR",
            entity_id=self.entity_id,
            display_order=2,
            price_source="yahoo",
        )
        self.db.add(xiaomi)
        self.db.flush()
        self.db.add_all(
            [
                AssetTransaction(
                    asset_type_id=xiaomi.id,
                    transaction_date=date(2026, 8, 14),
                    asset_amount=Decimal("185"),
                    invested_amount=Decimal("527.16"),
                    exchange_trade_id="traderepublic:20260814:KYG9830T1067",
                ),
                AssetTransaction(
                    asset_type_id=xiaomi.id,
                    transaction_date=date(2026, 11, 6),
                    asset_amount=Decimal("10"),
                    invested_amount=Decimal("30"),
                    exchange_trade_id="compra-el-mismo-dia-de-la-venta",
                ),
            ]
        )
        self.db.commit()

        trades, _ = parse_trade_republic_csv(CSV)
        result = TradeRepublicImportResult()
        with self.assertLogs("app.services.trade_republic_csv_service", level="INFO") as captured:
            fills = _plan_fills(
                self.db,
                trades,
                result,
                self.entity_id,
                set(),
                {str(xiaomi.id): (Decimal("185"), Decimal("527.16"))},
            )
        logged = "\n".join(captured.output)
        ids = {fill["exchange_trade_id"] for fill in fills}

        self.assertNotIn(f"{TRADE_ID_PREFIX}buy-xiaomi", ids)
        self.assertIn(f"{TRADE_ID_PREFIX}sell-xiaomi", ids)
        self.assertIn("se omite, ya hay una compra ese día", logged)
        self.assertNotIn("se omite, ya hay una venta ese día", logged)
        self.assertEqual(result.skipped_duplicate, 1)
        self.db.refresh(xiaomi)
        self.assertEqual(xiaomi.ticker, "3CP.HA")

        created = self.db.scalars(
            select(AssetType).where(AssetType.name == "NVIDIA", AssetType.entity_id == self.entity_id)
        ).one()
        self.assertEqual(created.price_source, "yahoo")

    def test_una_transaccion_ya_registrada_se_omite(self) -> None:
        trades, _ = parse_trade_republic_csv(CSV)
        only_buy = [trade for trade in trades if trade.transaction_id == "buy-xiaomi"]
        result = TradeRepublicImportResult()
        fills = _plan_fills(
            self.db,
            only_buy,
            result,
            self.entity_id,
            {f"{TRADE_ID_PREFIX}buy-xiaomi"},
            {},
        )
        self.assertEqual(fills, [])
        self.assertEqual(result.skipped_duplicate, 1)
        self.assertEqual(result.assets_created, 0)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(AssetType).where(AssetType.entity_id == self.entity_id)), 0)


if __name__ == "__main__":
    unittest.main()
