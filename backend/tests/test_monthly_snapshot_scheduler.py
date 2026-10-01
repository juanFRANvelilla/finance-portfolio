import unittest

from app.core import scheduler as scheduler_module
from app.core.scheduler import (
    MONTHLY_SNAPSHOT_ROLLOVER_CRON_HOUR,
    MONTHLY_SNAPSHOT_ROLLOVER_CRON_MINUTE,
    MONTHLY_SNAPSHOT_ROLLOVER_TIMEZONE,
)


class MonthlySnapshotSchedulerTests(unittest.TestCase):
    def test_monthly_rollover_cron_is_two_am_madrid(self) -> None:
        self.assertEqual(MONTHLY_SNAPSHOT_ROLLOVER_CRON_HOUR, 2)
        self.assertEqual(MONTHLY_SNAPSHOT_ROLLOVER_CRON_MINUTE, 0)
        self.assertEqual(MONTHLY_SNAPSHOT_ROLLOVER_TIMEZONE.key, "Europe/Madrid")

    def test_startup_helper_still_exists(self) -> None:
        self.assertTrue(callable(scheduler_module.start_monthly_snapshot_rollover_background))


if __name__ == "__main__":
    unittest.main()
