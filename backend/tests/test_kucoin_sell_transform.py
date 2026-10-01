import unittest
from datetime import datetime
from decimal import Decimal

from app.services.kucoin_sync_service import _transform_fills


class KucoinSellTransformTests(unittest.TestCase):
    def test_sell_registers_daily_key_not_per_fill_sale_row(self) -> None:
        asset_id = "11111111-1111-1111-1111-111111111111"
        asset_map = {"BTC": asset_id}
        position_totals = {asset_id: (Decimal("1.0"), Decimal("50000"))}

        raw = [
            {
                "symbol": "BTC-EUR",
                "side": "sell",
                "tradeId": "sell-1",
                "createdAt": int(datetime(2026, 3, 1, 12, 0).timestamp() * 1000),
                "funds": "25000",
                "size": "0.25",
                "fee": "1",
            }
        ]

        tx_rows, daily_keys, stats = _transform_fills(raw, asset_map, 1.0, position_totals)

        self.assertEqual(stats["skipped_invalid_sell"], 0)
        self.assertEqual(len(tx_rows), 1)
        self.assertEqual(daily_keys, {(asset_id, datetime(2026, 3, 1).date())})
        self.assertIsNone(tx_rows[0]["invested_amount"])
        self.assertLess(tx_rows[0]["asset_amount"], 0)

    def test_two_sells_same_day_same_asset_one_daily_key(self) -> None:
        asset_id = "22222222-2222-2222-2222-222222222222"
        asset_map = {"ETH": asset_id}
        position_totals = {asset_id: (Decimal("2"), Decimal("6000"))}
        day = datetime(2026, 4, 1)

        raw = [
            {
                "symbol": "ETH-EUR",
                "side": "SELL",
                "tradeId": "sell-a",
                "createdAt": int(day.replace(hour=10).timestamp() * 1000),
                "funds": "3100",
                "size": "1",
                "fee": "0.5",
            },
            {
                "symbol": "ETH-EUR",
                "side": "SELL",
                "tradeId": "sell-b",
                "createdAt": int(day.replace(hour=15).timestamp() * 1000),
                "funds": "3100",
                "size": "1",
                "fee": "0.5",
            },
        ]

        tx_rows, daily_keys, _ = _transform_fills(raw, asset_map, 1.0, position_totals)
        self.assertEqual(len(tx_rows), 2)
        self.assertEqual(len(daily_keys), 1)


if __name__ == "__main__":
    unittest.main()
