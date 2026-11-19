import unittest
from datetime import datetime
from decimal import Decimal

from app.services.kucoin_sync_service import _transform_fills


class KucoinConversionsTests(unittest.TestCase):
    def test_direct_eur_trade_has_no_conversion(self) -> None:
        asset_id = "11111111-1111-1111-1111-111111111111"
        asset_map = {"BTC": asset_id}
        raw = [
            {
                "symbol": "BTC-EUR",
                "side": "BUY",
                "tradeId": "trade-eur",
                "createdAt": int(datetime(2026, 11, 14, 4, 28).timestamp() * 1000),
                "funds": "399.75",
                "size": "0.0065",
                "price": "61500",
                "fee": "0.39975",
            }
        ]

        tx_rows, _, _ = _transform_fills(raw, asset_map)
        self.assertEqual(len(tx_rows), 1)
        tx = tx_rows[0]
        self.assertIsNone(tx.get("conversion"))
        self.assertEqual(tx["invested_amount"], Decimal("399.75000000"))
        self.assertEqual(tx["execution_price"], Decimal("61500.00000000"))

    def test_usdt_trade_with_preceding_bridge_order(self) -> None:
        asset_id = "11111111-1111-1111-1111-111111111111"
        asset_map = {"BTC": asset_id}
        t0 = int(datetime(2026, 11, 16, 10, 45).timestamp() * 1000)
        t1 = int(datetime(2026, 11, 16, 10, 47).timestamp() * 1000)

        raw = [
            {
                "symbol": "USDT-EUR",
                "side": "BUY",
                "tradeId": "bridge-order-1",
                "createdAt": t0,
                "funds": "910.90",
                "size": "1000.0",
                "price": "0.9109",
                "fee": "0.9109",
            },
            {
                "symbol": "BTC-USDT",
                "side": "BUY",
                "tradeId": "btc-buy-1",
                "createdAt": t1,
                "funds": "700.0",
                "size": "0.01087456",
                "price": "64360.0",
                "fee": "0.7",
            },
        ]

        tx_rows, _, _ = _transform_fills(raw, asset_map)
        self.assertEqual(len(tx_rows), 1)
        tx = tx_rows[0]
        conv = tx.get("conversion")
        self.assertIsNotNone(conv)
        self.assertEqual(conv["quote_currency"], "USDT")
        self.assertEqual(conv["original_invested_amount"], Decimal("700.00000000"))
        self.assertEqual(conv["original_execution_price"], Decimal("64360.00000000"))
        self.assertEqual(conv["fx_rate"], Decimal("0.910900"))
        self.assertEqual(conv["bridge_exchange_trade_id"], "bridge-order-1")

        # Invested amount en EUR = 700 * 0.9109 = 637.63
        expected_eur = Decimal(str(round(700.0 * 0.9109, 8)))
        self.assertEqual(tx["invested_amount"], expected_eur)

    def test_two_bridge_orders_match_closest_preceding(self) -> None:
        btc_id = "11111111-1111-1111-1111-111111111111"
        eth_id = "22222222-2222-2222-2222-222222222222"
        asset_map = {"BTC": btc_id, "ETH": eth_id}

        d1 = datetime(2026, 11, 16, 10, 45)
        d2 = datetime(2026, 11, 16, 10, 47)
        d3 = datetime(2026, 11, 18, 21, 56)
        d4 = datetime(2026, 11, 18, 21, 58)

        raw = [
            {
                "symbol": "USDT-EUR",
                "side": "BUY",
                "tradeId": "bridge-nov16",
                "createdAt": int(d1.timestamp() * 1000),
                "funds": "910.90",
                "size": "1000.0",
                "price": "0.9109",
            },
            {
                "symbol": "BTC-USDT",
                "side": "BUY",
                "tradeId": "btc-nov16",
                "createdAt": int(d2.timestamp() * 1000),
                "funds": "700.0",
                "size": "0.01087456",
                "price": "64360.0",
            },
            {
                "symbol": "USDT-EUR",
                "side": "BUY",
                "tradeId": "bridge-nov18",
                "createdAt": int(d3.timestamp() * 1000),
                "funds": "595.24",
                "size": "652.7473",
                "price": "0.9119",
            },
            {
                "symbol": "ETH-USDT",
                "side": "BUY",
                "tradeId": "eth-nov18",
                "createdAt": int(d4.timestamp() * 1000),
                "funds": "151.82",
                "size": "0.0865",
                "price": "1755.18",
            },
        ]

        tx_rows, _, _ = _transform_fills(raw, asset_map)
        self.assertEqual(len(tx_rows), 2)

        btc_tx = next(tx for tx in tx_rows if tx["exchange_trade_id"] == "btc-nov16")
        eth_tx = next(tx for tx in tx_rows if tx["exchange_trade_id"] == "eth-nov18")

        self.assertEqual(btc_tx["conversion"]["bridge_exchange_trade_id"], "bridge-nov16")
        self.assertEqual(btc_tx["conversion"]["fx_rate"], Decimal("0.910900"))

        self.assertEqual(eth_tx["conversion"]["bridge_exchange_trade_id"], "bridge-nov18")
        self.assertEqual(eth_tx["conversion"]["fx_rate"], Decimal(str(round(595.24 / 652.7473, 6))))


if __name__ == "__main__":
    unittest.main()
