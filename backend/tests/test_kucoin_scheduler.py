import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.scheduler import PORTFOLIO_SYNC_INTERVAL_HOURS, _portfolio_sync_cycle_job
from app.services.kucoin_sync_service import KucoinSyncResult


class PortfolioSyncCycleTests(unittest.TestCase):
    def test_portfolio_sync_interval_is_four_hours(self) -> None:
        self.assertEqual(PORTFOLIO_SYNC_INTERVAL_HOURS, 4)

    @patch("app.core.scheduler.run_scheduled_myinvestor_transfers_sync")
    @patch("app.core.scheduler.run_scheduled_myinvestor_sync")
    @patch("app.core.scheduler.run_scheduled_kucoin_fiat_cash_flows_sync")
    @patch("app.core.scheduler.run_scheduled_kucoin_sync")
    @patch("app.core.scheduler.run_ensure_current_month_entity_positions", return_value=0)
    @patch("app.core.scheduler.run_ensure_current_month_snapshots", return_value=0)
    @patch("app.core.scheduler.asyncio.to_thread", new_callable=AsyncMock)
    async def _run_cycle(
        self,
        mock_to_thread,
        _mock_snapshots,
        _mock_entities,
        mock_kucoin_sync,
        mock_kucoin_fiat,
        mock_myinvestor,
        mock_transfers,
    ):
        mock_sync_result = KucoinSyncResult(
            start_date=MagicMock(date=lambda: __import__("datetime").date(2026, 9, 28)),
            end_date=MagicMock(date=lambda: __import__("datetime").date(2026, 9, 30)),
            success=True,
        )
        mock_fiat_result = MagicMock(success=True, inserted=0, skipped_duplicate=0, start_date=MagicMock())
        mock_myinvestor_result = MagicMock(success=True, inserted=0, skipped_duplicate=0, raw_emails_count=0)
        mock_transfers_result = MagicMock(success=True, inserted=0, skipped_duplicate=0, raw_emails_count=0)

        async def to_thread_side_effect(func, *args, **kwargs):
            if func is mock_kucoin_sync:
                return mock_sync_result
            if func is mock_kucoin_fiat:
                return mock_fiat_result
            if func is mock_myinvestor:
                return mock_myinvestor_result
            if func is mock_transfers:
                return mock_transfers_result
            return func(*args, **kwargs)

        mock_to_thread.side_effect = to_thread_side_effect

        await _portfolio_sync_cycle_job()

        called_funcs = [call.args[0] for call in mock_to_thread.await_args_list]
        self.assertIn(mock_kucoin_sync, called_funcs)
        self.assertIn(mock_kucoin_fiat, called_funcs)
        self.assertIn(mock_myinvestor, called_funcs)
        self.assertIn(mock_transfers, called_funcs)

    def test_cycle_runs_opening_then_kucoin_then_myinvestor(self) -> None:
        import asyncio

        asyncio.run(self._run_cycle())


if __name__ == "__main__":
    unittest.main()
