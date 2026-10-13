import unittest
from decimal import Decimal

from app.services.transaction_pmp import (
    avg_buy_price_from_position,
    negative_invested_for_sell,
)


class TransactionPmpTests(unittest.TestCase):
    def test_avg_after_partial_sell_sequence(self) -> None:
        units = Decimal("4")
        invested = Decimal("2000")
        avg, out = negative_invested_for_sell(
            units_before=units, invested_before=invested, sold_units=Decimal("2")
        )
        self.assertEqual(avg, Decimal("500.0000"))
        self.assertEqual(out, Decimal("-1000.00000000"))
        units -= Decimal("2")
        invested += out
        self.assertEqual(invested / units, Decimal("500"))

    def test_rebuy_after_sell_updates_pmp(self) -> None:
        units = Decimal("2")
        invested = Decimal("1000")
        _, out = negative_invested_for_sell(
            units_before=Decimal("4"),
            invested_before=Decimal("2000"),
            sold_units=Decimal("2"),
        )
        units = Decimal("2")
        invested = Decimal("2000") + out
        units += Decimal("2")
        invested += Decimal("1100")
        self.assertEqual(avg_buy_price_from_position(units, invested), Decimal("525.0000"))


if __name__ == "__main__":
    unittest.main()
