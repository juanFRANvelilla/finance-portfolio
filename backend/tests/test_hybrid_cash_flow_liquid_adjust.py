import unittest
from datetime import date
from unittest.mock import MagicMock

from app.models.entity import Entity, EntityType
from app.models.monthly_entity_position import MonthlyEntityPosition
from app.services.hybrid_entity_auto_adjust import apply_hybrid_liquid_from_cash_flows


class HybridCashFlowLiquidAdjustTests(unittest.TestCase):
    def test_applies_signed_amount_to_hybrid_position(self) -> None:
        db = MagicMock()
        entity = Entity(id="myinvestor", name="MyInvestor", entity_type=EntityType.HYBRID)
        position = MonthlyEntityPosition(
            entity_id="myinvestor",
            year=2026,
            month=9,
            liquid_amount=100.0,
            invested_amount=500.0,
        )

        def get_model(_model, key):
            if _model is Entity and key == "myinvestor":
                return entity
            return None

        db.get.side_effect = get_model
        db.scalars.return_value.first.return_value = position

        result = apply_hybrid_liquid_from_cash_flows(
            db,
            [
                {
                    "entity_id": "myinvestor",
                    "amount": 800.0,
                    "flow_date": date(2026, 8, 28),
                    "source_reference": "myinvestor:transfer:abc",
                }
            ],
            position_as_of=date(2026, 9, 30),
        )

        self.assertEqual(result.flows_liquid_adjusted, 1)
        self.assertEqual(result.flows_skipped, 0)
        self.assertEqual(float(position.liquid_amount), 900.0)

    def test_skips_when_month_position_missing(self) -> None:
        db = MagicMock()
        entity = Entity(id="myinvestor", name="MyInvestor", entity_type=EntityType.HYBRID)
        db.get.return_value = entity
        db.scalars.return_value.first.return_value = None

        result = apply_hybrid_liquid_from_cash_flows(
            db,
            [
                {
                    "entity_id": "myinvestor",
                    "amount": 50.0,
                    "flow_date": date(2026, 1, 1),
                    "source_reference": "myinvestor:transfer:xyz",
                }
            ],
            position_as_of=date(2026, 3, 1),
        )

        self.assertEqual(result.flows_liquid_adjusted, 0)
        self.assertEqual(result.flows_skipped, 1)
        self.assertTrue(result.skip_reasons[0].startswith("sin monthly_entity_positions"))


if __name__ == "__main__":
    unittest.main()
