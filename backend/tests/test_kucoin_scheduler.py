import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.scheduler import KUCOIN_SYNC_INTERVAL_HOURS, _kucoin_sync_job
from app.services.kucoin_sync_service import KucoinSyncResult


class KucoinSchedulerJobTests(unittest.TestCase):
    def test_kucoin_interval_is_four_hours(self) -> None:
        self.assertEqual(KUCOIN_SYNC_INTERVAL_HOURS, 4)

    @patch("app.core.scheduler.run_scheduled_kucoin_fiat_cash_flows_sync")
    @patch("app.core.scheduler.run_scheduled_kucoin_sync")
    @patch("app.core.scheduler.asyncio.to_thread", new_callable=AsyncMock)
    async def _run_job(self, mock_to_thread, mock_sync, mock_fiat):
        mock_sync_result = KucoinSyncResult(
            start_date=MagicMock(date=lambda: __import__("datetime").date(2026, 9, 28)),
            end_date=MagicMock(date=lambda: __import__("datetime").date(2026, 9, 30)),
            success=True,
        )
        mock_fiat_result = MagicMock(success=True, inserted=0, skipped_duplicate=0, start_date=MagicMock())

        async def to_thread_side_effect(func, *args, **kwargs):
            if func is mock_sync:
                return mock_sync_result
            if func is mock_fiat:
                return mock_fiat_result
            return func(*args, **kwargs)

        mock_to_thread.side_effect = to_thread_side_effect

        await _kucoin_sync_job()

        self.assertGreaterEqual(mock_to_thread.await_count, 2)
        called_funcs = [call.args[0] for call in mock_to_thread.await_args_list]
        self.assertIn(mock_sync, called_funcs)
        self.assertIn(mock_fiat, called_funcs)

    def test_kucoin_job_runs_trades_and_fiat_in_same_task(self) -> None:
        import asyncio

        asyncio.run(self._run_job())


if __name__ == "__main__":
    unittest.main()
