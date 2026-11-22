"""The bot inside the platform: price-source switching, the Yahoo Finance cache, the bot API's
auth rules and the single-runner guard."""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.bot import models
from app.bot.api.router import api_router as bot_router
from app.bot.services import market_data as md
from app.core.security import create_access_token
from app.db.init_db import init_db
from app.models.all_models import User


class CountingProvider(md.MarketDataProvider):
    def __init__(self):
        self.calls = 0

    async def get_batch_quotes(self, tickers):
        self.calls += 1
        return {t.upper(): {"ticker": t.upper(), "price": 100.0 + self.calls} for t in tickers}

    async def get_quote(self, ticker):
        raise AssertionError("single quotes must come from the batch cache")

    async def get_intraday_candles(self, ticker, interval="5m"):
        return []

    async def get_daily_candles(self, ticker):
        return []


def test_yahoo_quotes_are_cached_between_polls():
    inner = CountingProvider()
    cached = md.CachedQuotes(inner, min_interval=60)
    first = asyncio.run(cached.get_batch_quotes(["BTC-USD", "ETH-USD"]))
    again = asyncio.run(cached.get_batch_quotes(["btc-usd", "ETH-USD"]))
    single = asyncio.run(cached.get_quote("ETH-USD"))
    assert inner.calls == 1
    assert again == first and single["price"] == first["ETH-USD"]["price"]


def test_expired_cache_polls_again():
    inner = CountingProvider()
    cached = md.CachedQuotes(inner, min_interval=0)
    asyncio.run(cached.get_batch_quotes(["BTC-USD"]))
    asyncio.run(cached.get_batch_quotes(["BTC-USD"]))
    assert inner.calls == 2


def test_switchable_provider_validates_names():
    feed = md.SwitchableMarketData("mock")
    feed.set_provider("YFINANCE")
    assert feed.name == "yfinance" and isinstance(feed._provider, md.CachedQuotes)
    feed.set_provider("mock")
    assert feed._provider is feed._mock  # the synthetic walk continues where it left off
    with pytest.raises(ValueError):
        feed.set_provider("bloomberg")


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    db = sessionmaker(bind=engine)()
    app = FastAPI()
    app.include_router(bot_router, prefix="/api/v1/bot")
    app.dependency_overrides[deps.get_db] = lambda: db
    feed = md.SwitchableMarketData("mock")
    monkeypatch.setattr("app.bot.api.settings.market_data", feed)
    user = User(email="u@example.com", hashed_password="x")
    db.add(user)
    db.commit()
    return TestClient(app), db, {"Authorization": f"Bearer {create_access_token(user.id)}"}, feed


def test_reading_is_public_but_changing_settings_needs_a_session(client):
    http, _, auth, feed = client
    assert http.get("/api/v1/bot/settings/").json()["market_data_provider"] == "mock"
    assert http.post("/api/v1/bot/settings/update", json={"market_data_provider": "yfinance"}).status_code == 401
    res = http.post("/api/v1/bot/settings/update", json={"market_data_provider": "yfinance", "leverage": 3}, headers=auth)
    assert res.status_code == 200 and res.json()["market_data_provider"] == "yfinance" and res.json()["leverage"] == 3
    assert feed.name == "yfinance"
    http.post("/api/v1/bot/settings/update", json={"leverage": 5.0}, headers=auth)  # restore the shared default


def test_switching_price_source_is_refused_with_open_positions(client):
    http, db, auth, feed = client
    account = models.BotAccount(email="bot@example.com")
    db.add(account)
    db.flush()
    db.add(models.PaperTrade(user_id=account.id, ticker="BTC-USD", paper_entry_price=1.0, quantity=1, status="OPEN"))
    db.commit()
    res = http.post("/api/v1/bot/settings/update", json={"market_data_provider": "yfinance"}, headers=auth)
    assert res.status_code == 409 and feed.name == "mock"
    bad = http.post("/api/v1/bot/settings/update", json={"market_data_provider": "nope"}, headers=auth)
    assert bad.status_code == 409  # still refused first, nothing changes


def test_watchlist_changes_need_a_session(client):
    http, _, auth, _ = client
    body = {"ticker": "ADA-USD", "asset_type": "Crypto", "priority": "High"}
    assert http.post("/api/v1/bot/watchlist/", json=body).status_code == 401
    assert http.post("/api/v1/bot/watchlist/", json=body, headers=auth).status_code == 200


def test_runner_does_not_start_when_disabled(monkeypatch):
    from app.bot import runner

    monkeypatch.setattr(runner.settings, "BOT_ENABLED", False)
    assert runner.start_bot() is None
    assert runner._acquire_runner_lock() is True  # SQLite / non-PostgreSQL: single process, no lock needed
