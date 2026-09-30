import unittest
from datetime import date
from decimal import Decimal

from app.services.kucoin_daily_asset_sales import (
    _SellSlice,
    aggregate_daily_kucoin_sale,
    kucoin_daily_sale_exchange_trade_id,
)


class AggregateDailyKucoinSaleTests(unittest.TestCase):
    ASSET_ID = "e8b03f1d-438e-4577-8a94-d83ab089247b"
    SALE_DATE = date(2026, 9, 30)

    def test_single_sell_produces_one_daily_row(self) -> None:
        row = aggregate_daily_kucoin_sale(
            asset_type_id=self.ASSET_ID,
            sale_date=self.SALE_DATE,
            sells=[
                _SellSlice(
                    asset_amount=Decimal("-0.0006"),
                    invested_amount=Decimal("-44.670024"),
                    fee_amount=Decimal("0.04467002"),
                )
            ],
            position_units_before=Decimal("0.002264"),
            position_invested_before=Decimal("150.0"),
        )

        self.assertIsNotNone(row)
        assert row is not None
        self.assertAlmostEqual(row["units"], 0.0006, places=8)
        self.assertEqual(
            row["exchange_trade_id"],
            kucoin_daily_sale_exchange_trade_id(self.ASSET_ID, self.SALE_DATE),
        )

    def test_multiple_sells_same_day_same_asset_merge_into_one_row(self) -> None:
        """Dos transacciones de venta → una sola fila asset_sales (mismo exchange_trade_id)."""
        row = aggregate_daily_kucoin_sale(
            asset_type_id=self.ASSET_ID,
            sale_date=self.SALE_DATE,
            sells=[
                _SellSlice(
                    asset_amount=Decimal("-0.0006"),
                    invested_amount=Decimal("-44.67"),
                    fee_amount=Decimal("0.04"),
                ),
                _SellSlice(
                    asset_amount=Decimal("-0.0003"),
                    invested_amount=Decimal("-22.335"),
                    fee_amount=Decimal("0.02"),
                ),
            ],
            position_units_before=Decimal("0.01"),
            position_invested_before=Decimal("662.236408"),
        )

        self.assertIsNotNone(row)
        assert row is not None
        self.assertAlmostEqual(row["units"], 0.0009, places=8)
        self.assertAlmostEqual(row["fee"], 0.06, places=4)
        expected_vwap = (44.67 + 22.335) / 0.0009
        self.assertAlmostEqual(row["sale_price"], round(expected_vwap, 4), places=3)
        self.assertAlmostEqual(row["position_sold_pct"], 9.0, places=1)
        self.assertEqual(
            row["exchange_trade_id"],
            kucoin_daily_sale_exchange_trade_id(self.ASSET_ID, self.SALE_DATE),
        )

    def test_two_assets_same_day_have_different_exchange_trade_ids(self) -> None:
        other_asset = "edd8d035-1791-41d8-b845-83e19364613b"
        ref_a = kucoin_daily_sale_exchange_trade_id(self.ASSET_ID, self.SALE_DATE)
        ref_b = kucoin_daily_sale_exchange_trade_id(other_asset, self.SALE_DATE)
        self.assertNotEqual(ref_a, ref_b)

    def test_full_position_sold_is_100_pct(self) -> None:
        row = aggregate_daily_kucoin_sale(
            asset_type_id=self.ASSET_ID,
            sale_date=self.SALE_DATE,
            sells=[
                _SellSlice(
                    asset_amount=Decimal("-1.5"),
                    invested_amount=Decimal("-3000"),
                    fee_amount=Decimal("1"),
                )
            ],
            position_units_before=Decimal("1.5"),
            position_invested_before=Decimal("3000"),
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["position_sold_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
