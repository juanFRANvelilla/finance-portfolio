import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.asset_type import AssetType
from app.models.investment_category import InvestmentCategory
from app.services.market_data.base import MarketDataProvider
from app.services.market_price_service import MarketPriceService


class MockProvider(MarketDataProvider):
    def __init__(self, price: float = 100.0, currency: str = "USD"):
        self.price = price
        self.currency = currency
        self.call_count = 0

    def get_price(self, ticker: str):
        self.call_count += 1
        return {"price": self.price, "currency": self.currency}


class TestMarketPriceService(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Seed category and asset types
        cat = InvestmentCategory(id="cat-crypto", name="Cripto", display_order=1)
        self.db.add(cat)
        self.db.commit()

        self.asset1 = AssetType(
            category_id="cat-crypto",
            name="Bitcoin",
            ticker="BTC-EUR",
            currency="EUR",
            price_source="mock",
            is_active=True,
        )
        self.asset2 = AssetType(
            category_id="cat-crypto",
            name="Ethereum",
            ticker="ETH-EUR",
            currency="EUR",
            price_source="mock",
            is_active=True,
        )
        self.db.add_all([self.asset1, self.asset2])
        self.db.commit()

        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_file = Path(self.temp_dir.name) / "market_prices_cache.json"

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_loads_cache_from_disk_and_serves_instantly(self):
        # Pre-populate disk cache
        data = {
            "mock:BTC-EUR": {"price": 60000.0, "currency": "EUR", "fetched_at": 1000.0},
            "mock:ETH-EUR": {"price": 3000.0, "currency": "EUR", "fetched_at": 1000.0},
        }
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        service = MarketPriceService(cache_file_path=self.cache_file)
        mock_provider = MockProvider()
        service._providers["mock"] = mock_provider

        # Call get_prices without force_refresh
        prices = service.get_prices(self.db, force_refresh=False)

        # Should return both immediately from cache without calling provider
        self.assertEqual(len(prices), 2)
        self.assertEqual(mock_provider.call_count, 0)

        btc = next(p for p in prices if p.ticker == "BTC-EUR")
        self.assertEqual(btc.price, 60000.0)

    def test_fetches_missing_ticker_and_saves_to_disk(self):
        service = MarketPriceService(cache_file_path=self.cache_file)
        mock_provider = MockProvider(price=50000.0, currency="EUR")
        service._providers["mock"] = mock_provider

        prices = service.get_prices(self.db, force_refresh=False)

        # Both were missing, so provider should have been called
        self.assertEqual(len(prices), 2)
        self.assertGreater(mock_provider.call_count, 0)

        # Verify disk cache is saved
        self.assertTrue(self.cache_file.exists())
        with open(self.cache_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertIn("mock:BTC-EUR", saved)
        self.assertEqual(saved["mock:BTC-EUR"]["price"], 50000.0)

    def test_refresh_all_prices_updates_cache_and_disk(self):
        service = MarketPriceService(cache_file_path=self.cache_file)
        mock_provider = MockProvider(price=99999.0, currency="EUR")
        service._providers["mock"] = mock_provider

        prices = service.refresh_all_prices(self.db)
        self.assertEqual(len(prices), 2)
        self.assertEqual(prices[0].price, 99999.0)

        # Invalidate ticker
        service.invalidate_ticker("mock", "BTC-EUR")
        with open(self.cache_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertNotIn("mock:BTC-EUR", saved)
