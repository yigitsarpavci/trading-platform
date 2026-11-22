"""Market data for the bot: a synthetic random walk ("mock", the default) or live Yahoo Finance
quotes ("yfinance"). The provider can be switched at runtime from the bot settings page."""
import time
from typing import Any, Dict, List

from app.bot.config import settings
from .base import MarketDataProvider
from .mock_provider import MockProvider
from .yfinance_provider import YFinanceProvider

PROVIDERS = ("mock", "yfinance")


class CachedQuotes(MarketDataProvider):
    """Serves quotes from the last batch for `min_interval` seconds. The bot asks for prices every
    2 seconds (plus one quote per open trade); Yahoo Finance rate-limits clients that poll that often,
    and its prices only move every few seconds anyway."""

    def __init__(self, inner: MarketDataProvider, min_interval: float):
        self.inner = inner
        self.min_interval = min_interval
        self._cache: Dict[str, tuple[float, Dict[str, Any]]] = {}

    def _fresh(self, ticker: str):
        hit = self._cache.get(ticker.upper())
        return hit[1] if hit and time.monotonic() - hit[0] < self.min_interval else None

    async def get_batch_quotes(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        cached = {t.upper(): self._fresh(t) for t in tickers}
        if all(cached.values()):
            return cached
        quotes = await self.inner.get_batch_quotes(tickers)
        now = time.monotonic()
        for t, q in quotes.items():
            if isinstance(q.get("price"), (int, float)) and q["price"] > 0:
                self._cache[t.upper()] = (now, q)
        return quotes

    async def get_quote(self, ticker: str) -> Dict[str, Any]:
        hit = self._fresh(ticker)
        if hit:
            return hit
        return (await self.get_batch_quotes([ticker])).get(ticker.upper(), {"error": "no quote", "ticker": ticker})

    async def get_intraday_candles(self, ticker: str, interval: str = "5m") -> List[Dict[str, Any]]:
        return await self.inner.get_intraday_candles(ticker, interval)

    async def get_daily_candles(self, ticker: str) -> List[Dict[str, Any]]:
        return await self.inner.get_daily_candles(ticker)


class SwitchableMarketData(MarketDataProvider):
    def __init__(self, name: str):
        self._mock = MockProvider()
        self.set_provider(name)

    def set_provider(self, name: str) -> None:
        name = name.strip().lower()
        if name not in PROVIDERS:
            raise ValueError(f"Unknown market data provider {name!r}; use one of {', '.join(PROVIDERS)}")
        self.name = name
        self._provider = (
            self._mock if name == "mock"
            else CachedQuotes(YFinanceProvider(), settings.YFINANCE_MIN_INTERVAL_SECONDS)
        )

    async def get_quote(self, ticker: str) -> Dict[str, Any]:
        return await self._provider.get_quote(ticker)

    async def get_batch_quotes(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        return await self._provider.get_batch_quotes(tickers)

    async def get_intraday_candles(self, ticker: str, interval: str = "5m") -> List[Dict[str, Any]]:
        return await self._provider.get_intraday_candles(ticker, interval)

    async def get_daily_candles(self, ticker: str) -> List[Dict[str, Any]]:
        return await self._provider.get_daily_candles(ticker)


def get_market_data_provider() -> SwitchableMarketData:
    return SwitchableMarketData(settings.MARKET_DATA_PROVIDER)


market_data = get_market_data_provider()
