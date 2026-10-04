import unittest
from decimal import Decimal

from app.services.hybrid_entity_auto_adjust import _native_cash_delta_for_fill


class NativeCashDeltaTests(unittest.TestCase):
    def test_myinvestor_buy_uses_invested_only(self) -> None:
        fill = {
            "asset_amount": Decimal("3"),
            "invested_amount": Decimal("434.65"),
            "fee_amount": Decimal("1.00"),
            "execution_price": Decimal("144.55"),
        }
        delta = _native_cash_delta_for_fill(fill, source="myinvestor")
        self.assertEqual(delta, Decimal("-434.65"))

    def test_kucoin_buy_adds_fee_to_cash_out(self) -> None:
        fill = {
            "asset_amount": Decimal("0.01"),
            "invested_amount": Decimal("500"),
            "fee_amount": Decimal("1"),
            "execution_price": Decimal("50000"),
        }
        delta = _native_cash_delta_for_fill(fill, source="kucoin")
        self.assertEqual(delta, Decimal("-501"))

    def test_kucoin_sell_net_proceeds(self) -> None:
        fill = {
            "asset_amount": Decimal("-0.0006"),
            "invested_amount": None,
            "fee_amount": Decimal("0.04"),
            "execution_price": Decimal("74450"),
        }
        delta = _native_cash_delta_for_fill(fill, source="kucoin")
        expected = Decimal("0.0006") * Decimal("74450") - Decimal("0.04")
        self.assertEqual(delta, expected)

    def test_myinvestor_sell_returns_none(self) -> None:
        fill = {
            "asset_amount": Decimal("-1"),
            "invested_amount": Decimal("100"),
            "fee_amount": Decimal("1"),
            "execution_price": Decimal("100"),
        }
        self.assertIsNone(_native_cash_delta_for_fill(fill, source="myinvestor"))


if __name__ == "__main__":
    unittest.main()
