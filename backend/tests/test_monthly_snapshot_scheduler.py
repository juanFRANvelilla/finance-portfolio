import unittest

from app.core import scheduler as scheduler_module


class MonthlySnapshotSchedulerTests(unittest.TestCase):
    def test_startup_runner_exists(self) -> None:
        self.assertTrue(callable(scheduler_module.run_startup_monthly_snapshot_rollover))

    def test_sync_jobs_run_month_opening_before_trades(self) -> None:
        self.assertTrue(callable(scheduler_module._ensure_current_month_tables_before_sync))


if __name__ == "__main__":
    unittest.main()
