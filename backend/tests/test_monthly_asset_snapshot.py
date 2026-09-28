"""Regla de last_update para monthly_asset_investments, sin BD (función pura).

Ver .cursor/rules/monthly-asset-investments-sync.mdc para el diseño completo.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal

from app.services.monthly_asset_snapshot import (
    SnapshotFill,
    _next_year_month,
    _previous_year_month,
    decide_snapshot_update,
    is_current_natural_month,
)

ASSET_ID = "11111111-1111-1111-1111-111111111111"


def make_fill(executed_at: datetime | None, invested: str, units: str) -> SnapshotFill:
    return SnapshotFill(
        asset_type_id=ASSET_ID,
        year=2026,
        month=9,
        executed_at=executed_at,
        invested_amount=Decimal(invested),
        asset_amount=Decimal(units),
    )


class DecideSnapshotUpdateTest(unittest.TestCase):
    def test_brand_new_row_sums_every_fill(self) -> None:
        """Fila recién creada (last_update=None): todos los fills del grupo cuentan."""
        fills = [
            make_fill(datetime(2026, 9, 10, 12, 0, 0), "400", "1"),
            make_fill(datetime(2026, 9, 28, 9, 0, 0), "100", "0.5"),
        ]
        decision = decide_snapshot_update(
            existing_amount=Decimal("0"),
            existing_units=Decimal("0"),
            existing_last_update=None,
            fills=fills,
        )
        self.assertTrue(decision.should_update)
        self.assertEqual(decision.new_amount, Decimal("500.00"))
        self.assertEqual(decision.new_units, Decimal("1.5000"))
        self.assertEqual(decision.new_last_update, datetime(2026, 9, 28, 9, 0, 0))

    def test_manual_edit_after_transaction_blocks_it(self) -> None:
        """Editaste a mano el 25/09; llega una compra ejecutada el 24/09 -> no se toca."""
        fill = make_fill(datetime(2026, 9, 24, 16, 53, 1), "100", "4")
        decision = decide_snapshot_update(
            existing_amount=Decimal("480.00"),
            existing_units=Decimal("2"),
            existing_last_update=datetime(2026, 9, 25, 10, 0, 0),
            fills=[fill],
        )
        self.assertFalse(decision.should_update)
        self.assertEqual(decision.new_amount, Decimal("480.00"))
        self.assertEqual(decision.new_last_update, datetime(2026, 9, 25, 10, 0, 0))

    def test_reinserting_the_same_transaction_does_not_double_count(self) -> None:
        """Se borró y se volvió a insertar el mismo fill: executed_at == last_update -> no cuenta."""
        same_moment = datetime(2026, 9, 24, 16, 53, 1)
        fill = make_fill(same_moment, "100", "4")
        decision = decide_snapshot_update(
            existing_amount=Decimal("480.00"),
            existing_units=Decimal("2"),
            existing_last_update=same_moment,
            fills=[fill],
        )
        self.assertFalse(decision.should_update)

    def test_transaction_strictly_after_last_update_is_applied(self) -> None:
        """No se editó nada a mano tras la última automatización: la compra nueva sí suma."""
        fill = make_fill(datetime(2026, 9, 28, 8, 0, 0), "100", "4")
        decision = decide_snapshot_update(
            existing_amount=Decimal("480.00"),
            existing_units=Decimal("2"),
            existing_last_update=datetime(2026, 9, 24, 16, 53, 1),
            fills=[fill],
        )
        self.assertTrue(decision.should_update)
        self.assertEqual(decision.new_amount, Decimal("580.00"))
        self.assertEqual(decision.new_units, Decimal("6.0000"))
        self.assertEqual(decision.new_last_update, datetime(2026, 9, 28, 8, 0, 0))

    def test_mixed_group_only_applies_the_fills_after_last_update(self) -> None:
        """Del grupo, solo se suman los fills posteriores al last_update actual."""
        before = make_fill(datetime(2026, 9, 20, 10, 0, 0), "50", "1")
        after = make_fill(datetime(2026, 9, 28, 8, 0, 0), "100", "4")
        decision = decide_snapshot_update(
            existing_amount=Decimal("480.00"),
            existing_units=Decimal("2"),
            existing_last_update=datetime(2026, 9, 24, 16, 53, 1),
            fills=[before, after],
        )
        self.assertTrue(decision.should_update)
        # Solo `after` cuenta: 480 + 100, no 480 + 50 + 100.
        self.assertEqual(decision.new_amount, Decimal("580.00"))
        self.assertEqual(decision.new_units, Decimal("6.0000"))
        self.assertEqual(decision.new_last_update, datetime(2026, 9, 28, 8, 0, 0))

    def test_extreme_case_older_never_applied_transaction_is_not_retroactively_applied(self) -> None:
        """Caso extremo aceptado: last_update ya avanzó al 27 por otra transacción,
        y aparece una transacción del 23 que nunca se había aplicado. No se suma."""
        fill = make_fill(datetime(2026, 9, 23, 9, 0, 0), "999", "99")
        decision = decide_snapshot_update(
            existing_amount=Decimal("480.00"),
            existing_units=Decimal("2"),
            existing_last_update=datetime(2026, 9, 27, 0, 0, 0),
            fills=[fill],
        )
        self.assertFalse(decision.should_update)

    def test_fill_without_executed_at_is_always_applied_defensively(self) -> None:
        """Un fill sin executed_at (no debería pasar con los providers actuales) se aplica
        siempre, en vez de bloquear el resto del grupo por un dato incompleto."""
        fill = make_fill(None, "50", "1")
        decision = decide_snapshot_update(
            existing_amount=Decimal("480.00"),
            existing_units=Decimal("2"),
            existing_last_update=datetime(2026, 9, 27, 0, 0, 0),
            fills=[fill],
        )
        self.assertTrue(decision.should_update)
        self.assertEqual(decision.new_amount, Decimal("530.00"))
        # Sin executed_at no hay con qué avanzar last_update: se conserva el que había.
        self.assertEqual(decision.new_last_update, datetime(2026, 9, 27, 0, 0, 0))

    def test_empty_fills_list_raises(self) -> None:
        with self.assertRaises(ValueError):
            decide_snapshot_update(
                existing_amount=Decimal("0"),
                existing_units=Decimal("0"),
                existing_last_update=None,
                fills=[],
            )


class CurrentNaturalMonthTest(unittest.TestCase):
    def test_same_month_as_today(self) -> None:
        self.assertTrue(is_current_natural_month(date(2026, 9, 15), today=date(2026, 9, 28)))

    def test_past_month_is_not_current(self) -> None:
        self.assertFalse(is_current_natural_month(date(2026, 8, 31), today=date(2026, 9, 28)))

    def test_future_month_is_not_current(self) -> None:
        self.assertFalse(is_current_natural_month(date(2026, 10, 1), today=date(2026, 9, 28)))

    def test_year_boundary(self) -> None:
        self.assertFalse(is_current_natural_month(date(2025, 12, 31), today=date(2026, 1, 5)))
        self.assertTrue(is_current_natural_month(date(2026, 1, 1), today=date(2026, 1, 5)))


class YearMonthHelpersTest(unittest.TestCase):
    def test_previous_year_month_wraps_january(self) -> None:
        self.assertEqual(_previous_year_month(2026, 1), (2025, 12))
        self.assertEqual(_previous_year_month(2026, 9), (2026, 8))

    def test_next_year_month_wraps_december(self) -> None:
        self.assertEqual(_next_year_month(2026, 12), (2027, 1))
        self.assertEqual(_next_year_month(2026, 9), (2026, 10))


if __name__ == "__main__":
    unittest.main()
