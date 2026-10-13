"""Construcción de fills MyInvestor (compras/ventas) sin IMAP ni BD."""

from __future__ import annotations

import unittest
from decimal import Decimal

from app.myinvestor.trades.parse_trade import parse_myinvestor_trade
from app.services.myinvestor_sync_service import (
    TRADE_ID_PREFIX,
    _ResolvedTrade,
    _build_fills_from_trades,
)
from tests.test_myinvestor_parse import SAMPLE_GOLD_EUR, SAMPLE_MSFT_SELL_EUR


class MyInvestorBuildFillsTest(unittest.TestCase):
    def test_venta_usa_pmp_de_posicion_en_bd(self) -> None:
        sell_trade = parse_myinvestor_trade(SAMPLE_MSFT_SELL_EUR)
        assert sell_trade is not None

        asset_id = "11111111-1111-1111-1111-111111111111"
        resolved = [
            _ResolvedTrade(trade=sell_trade, asset_type_id=asset_id, asset_currency="EUR"),
        ]
        fills, skipped_dup, skipped_invalid = _build_fills_from_trades(
            resolved,
            existing_trade_ids=set(),
            position_totals={asset_id: (Decimal("10"), Decimal("4000"))},
        )
        self.assertEqual(skipped_dup, 0)
        self.assertEqual(skipped_invalid, 0)
        self.assertEqual(len(fills), 1)

        sell_fill = fills[0]
        self.assertLess(sell_fill["asset_amount"], 0)
        self.assertEqual(sell_fill["invested_amount"], Decimal("-800.00000000"))
        self.assertEqual(sell_fill["net_liquidity"], Decimal("967.40000000"))
        payload = sell_fill["sale_payload"]
        self.assertEqual(payload["net_liquidity"], 967.4)
        self.assertEqual(payload["fee"], 3.0)
        self.assertEqual(payload["avg_buy_price"], 400.0)
        self.assertEqual(payload["sale_price"], float(Decimal("485.2000")))
        self.assertEqual(
            sell_fill["exchange_trade_id"],
            f"{TRADE_ID_PREFIX}{sell_trade.reference}",
        )

    def test_compra_en_lote_actualiza_pmp_para_venta_posterior(self) -> None:
        buy_trade = parse_myinvestor_trade(SAMPLE_GOLD_EUR)
        sell_trade = parse_myinvestor_trade(SAMPLE_MSFT_SELL_EUR)
        assert buy_trade is not None and sell_trade is not None

        asset_id = "11111111-1111-1111-1111-111111111111"
        resolved = [
            _ResolvedTrade(trade=buy_trade, asset_type_id=asset_id, asset_currency="EUR"),
            _ResolvedTrade(trade=sell_trade, asset_type_id=asset_id, asset_currency="EUR"),
        ]
        fills, _, skipped_invalid = _build_fills_from_trades(
            resolved,
            existing_trade_ids=set(),
            position_totals={},
        )
        self.assertEqual(skipped_invalid, 0)
        self.assertEqual(len(fills), 2)
        self.assertGreater(fills[0]["asset_amount"], 0)
        self.assertLess(fills[1]["asset_amount"], 0)

    def test_venta_sin_posicion_se_omite(self) -> None:
        sell_trade = parse_myinvestor_trade(SAMPLE_MSFT_SELL_EUR)
        assert sell_trade is not None
        asset_id = "22222222-2222-2222-2222-222222222222"
        resolved = [
            _ResolvedTrade(trade=sell_trade, asset_type_id=asset_id, asset_currency="EUR"),
        ]
        fills, _, skipped_invalid = _build_fills_from_trades(
            resolved,
            existing_trade_ids=set(),
            position_totals={},
        )
        self.assertEqual(fills, [])
        self.assertEqual(skipped_invalid, 1)

    def test_referencia_ya_importada_no_duplica_pmp(self) -> None:
        buy_trade = parse_myinvestor_trade(SAMPLE_GOLD_EUR)
        assert buy_trade is not None
        asset_id = "33333333-3333-3333-3333-333333333333"
        ref = f"{TRADE_ID_PREFIX}{buy_trade.reference}"
        resolved = [
            _ResolvedTrade(trade=buy_trade, asset_type_id=asset_id, asset_currency="EUR"),
        ]
        fills, skipped_dup, _ = _build_fills_from_trades(
            resolved,
            existing_trade_ids={ref},
            position_totals={asset_id: (Decimal("3"), Decimal("434.65"))},
        )
        self.assertEqual(fills, [])
        self.assertEqual(skipped_dup, 1)


if __name__ == "__main__":
    unittest.main()
