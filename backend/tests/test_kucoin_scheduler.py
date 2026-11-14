import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.scheduler import (
    PORTFOLIO_SYNC_INTERVAL_HOURS,
    _portfolio_sync_cycle_job,
    _run_portfolio_imports_blocking,
)


class PortfolioSyncCycleTests(unittest.TestCase):
    def test_portfolio_sync_interval_is_four_hours(self) -> None:
        self.assertEqual(PORTFOLIO_SYNC_INTERVAL_HOURS, 4)

    @patch("app.core.scheduler._run_portfolio_imports_blocking")
    @patch("app.core.scheduler.run_ensure_current_month_entity_positions", return_value=0)
    @patch("app.core.scheduler.run_ensure_current_month_snapshots", return_value=0)
    @patch("app.core.scheduler.asyncio.to_thread", new_callable=AsyncMock)
    @patch("app.core.scheduler.asyncio.get_running_loop")
    async def _run_cycle(
        self,
        mock_get_loop,
        mock_to_thread,
        _mock_snapshots,
        _mock_entities,
        mock_imports_blocking,
    ):
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop

        async def run_in_executor(executor, func):
            self.assertIsNotNone(executor)
            func()
            return None

        mock_loop.run_in_executor = AsyncMock(side_effect=run_in_executor)

        await _portfolio_sync_cycle_job()

        mock_imports_blocking.assert_called_once()

    def test_cycle_runs_opening_then_imports_in_worker(self) -> None:
        import asyncio

        asyncio.run(self._run_cycle())

    @patch("app.core.scheduler.run_scheduled_myinvestor_transfers_sync")
    @patch("app.core.scheduler.run_scheduled_myinvestor_sync")
    @patch("app.core.scheduler.run_scheduled_kucoin_fiat_cash_flows_sync")
    @patch("app.core.scheduler.run_scheduled_kucoin_sync")
    def test_imports_blocking_runs_kucoin_then_myinvestor_in_order(
        self,
        mock_kucoin_sync,
        mock_kucoin_fiat,
        mock_myinvestor,
        mock_transfers,
    ) -> None:
        call_order: list[str] = []

        def kucoin_side_effect():
            call_order.append("kucoin_trades")
            return MagicMock(success=True, inserted=0, sales_inserted=0, skipped_duplicate=0, sales_skipped_duplicate=0, raw_fills_count=0, start_date=MagicMock(date=lambda: __import__("datetime").date(2026, 9, 28)), error=None)

        def kucoin_fiat_side_effect():
            call_order.append("kucoin_fiat")
            return MagicMock(success=True, inserted=0, skipped_duplicate=0, start_date=MagicMock(date=lambda: __import__("datetime").date(2026, 9, 28)), error=None)

        def myinvestor_side_effect():
            call_order.append("myinvestor_trades")
            return MagicMock(success=True, inserted=0, sales_inserted=0, skipped_duplicate=0, raw_emails_count=0, error=None)

        def transfers_side_effect():
            call_order.append("myinvestor_transfers")
            return MagicMock(success=True, inserted=0, skipped_duplicate=0, liquid_adjusted=0, raw_emails_count=0, error=None)

        mock_kucoin_sync.side_effect = kucoin_side_effect
        mock_kucoin_fiat.side_effect = kucoin_fiat_side_effect
        mock_myinvestor.side_effect = myinvestor_side_effect
        mock_transfers.side_effect = transfers_side_effect

        _run_portfolio_imports_blocking()

        self.assertEqual(
            call_order,
            ["kucoin_trades", "kucoin_fiat", "myinvestor_trades", "myinvestor_transfers"],
        )


if __name__ == "__main__":
    unittest.main()