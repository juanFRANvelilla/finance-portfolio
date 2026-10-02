"""Totales por categoría: suma de monthly_asset_investments con USD→EUR."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.routers.investments import _computed_category_totals


def _amount_to_eur_stub(amount: float, currency: str, year: int, month: int) -> float:
    if currency == "USD":
        return round(amount * 0.92, 2)
    return round(float(amount), 2)


class ComputedCategoryTotalsTest(unittest.TestCase):
    @patch("app.routers.investments.amount_to_eur", side_effect=_amount_to_eur_stub)
    def test_sums_assets_in_eur_and_converts_usd_per_category(self, _mock_amount_to_eur) -> None:
        db = MagicMock()
        db.execute.return_value.all.return_value = [
            ("fondos", "EUR", 1000.0),
            ("crypto", "EUR", 200.0),
            ("crypto", "USD", 100.0),
        ]

        totals = _computed_category_totals(db, 2026, 10)

        self.assertEqual(totals["fondos"], 1000.0)
        self.assertEqual(totals["crypto"], 292.0)
        self.assertNotIn("acciones", totals)

    @patch("app.routers.investments.amount_to_eur", side_effect=_amount_to_eur_stub)
    def test_empty_month_returns_empty_dict(self, _mock_amount_to_eur) -> None:
        db = MagicMock()
        db.execute.return_value.all.return_value = []

        self.assertEqual(_computed_category_totals(db, 2026, 10), {})


if __name__ == "__main__":
    unittest.main()
