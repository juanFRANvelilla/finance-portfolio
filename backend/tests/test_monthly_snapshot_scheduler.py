import unittest

from app.core import scheduler as scheduler_module


class MonthlySnapshotSchedulerTests(unittest.TestCase):
    def test_startup_runner_exists(self) -> None:
        self.assertTrue(callable(scheduler_module.run_startup_monthly_snapshot_rollover))

    def test_portfolio_cycle_job_exists(self) -> None:
        self.assertTrue(callable(scheduler_module._portfolio_sync_cycle_job))


if __name__ == "__main__":
    unittest.main()
