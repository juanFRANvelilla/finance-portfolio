import unittest

from app.models.entity import EntityType
from app.services.monthly_entity_position_snapshot import _default_invested_for_entity


class MonthlyEntityPositionSnapshotTests(unittest.TestCase):
    def test_default_invested_liquid_is_none(self) -> None:
        self.assertIsNone(_default_invested_for_entity(EntityType.LIQUID))

    def test_default_invested_hybrid_is_zero(self) -> None:
        from decimal import Decimal

        self.assertEqual(_default_invested_for_entity(EntityType.HYBRID), Decimal("0"))


if __name__ == "__main__":
    unittest.main()
