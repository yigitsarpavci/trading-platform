"""Execution: trading on the in-process exchange (real order book, settlement, market maker) and how the bot handles
missing, partial and full fills."""
import asyncio

import pytest

from app.bot import models
from app.bot.services import execution as ex
from app.bot.services import paper_trading as pt
from app.bot.tests.test_paper_trading import db, make_trade, run, tick  # noqa: F401  (fixtures and helpers)


# ------------------------------------------------------------------ in-process exchange


@pytest.fixture()
def exchange(monkeypatch):
    """A real exchange (matching, settlement, market maker) on an in-memory SQLite database."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.init_db import init_db

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    return ex.ExchangeExecution(session_factory=factory, tolerance_bps=20), factory


def test_symbols_drop_the_quote_currency():
    assert ex.exchange_symbol("btc-usd") == "BTC"
    assert ex.exchange_symbol("AAPL") == "AAPL"


def test_round_trip_on_the_real_order_book_pays_the_spread(exchange):
    from app.core.config import settings as platform
    from app.models.all_models import Trade, User
    from app.services import trading

    client, factory = exchange
    asyncio.run(client.publish_prices({"BTC-USD": 100_000.0, "ETH-USD": 0.0}))
    half = platform.MARKET_MAKER_SPREAD_BPS / 2 / 10_000

    bought = asyncio.run(client.buy("BTC-USD", 0.1, 100_000.0))
    assert bought.quantity == pytest.approx(0.1) and bought.price == pytest.approx(100_000 * (1 + half))
    sold = asyncio.run(client.sell("BTC-USD", 0.1, 100_000.0))
    assert sold.price == pytest.approx(100_000 * (1 - half))

    db = factory()
    bot = db.query(User).filter(User.email == "trading-engine@example.com").one()
    assert db.query(Trade).count() == 2
    assert trading.held_quantity(db, bot.id, db.query(trading.Asset).filter_by(ticker_symbol="BTC").one().id) == 0
    assert bot.cash_balance == pytest.approx(100_000 - 0.1 * 100_000 * 2 * half)


def test_unknown_asset_and_failed_checks_return_no_fill(exchange):
    client, _ = exchange
    assert asyncio.run(client.buy("DOGE-USD", 1.0, 1.0)) is None  # never published
    asyncio.run(client.publish_prices({"BTC-USD": 100_000.0}))
    assert asyncio.run(client.buy("BTC-USD", 5.0, 100_000.0)) is None  # 500k > the bot's 100k cash
    assert asyncio.run(client.sell("BTC-USD", 1.0, 100_000.0)) is None  # holds no BTC


# ------------------------------------------------------------------ engine with exchange fills


class StubExecution:
    mode = "exchange"

    def __init__(self, fill_ratio=1.0, price_offset=0.0):
        self.fill_ratio = fill_ratio
        self.price_offset = price_offset
        self.published = []

    async def publish_prices(self, prices):
        self.published.append(prices)

    async def buy(self, ticker, quantity, price):
        return ex.Fill(quantity * self.fill_ratio, price + self.price_offset) if self.fill_ratio else None

    async def sell(self, ticker, quantity, price):
        return ex.Fill(quantity * self.fill_ratio, price - self.price_offset) if self.fill_ratio else None


def _signal(db, price=100.0, suggested="1000"):
    user = models.BotAccount(email="e@x.io", portfolio_value=100_000.0)
    db.add(user)
    db.flush()
    signal = models.Signal(user_id=user.id, ticker="SOL-USD", signal_type="BUY", entry_price=price,
                           stop_loss=price * 0.99, take_profit=price * 1.02, suggested_amount=suggested)
    db.add(signal)
    db.commit()
    return signal


def test_entry_uses_the_exchange_fill_price_and_quantity(db, monkeypatch):
    monkeypatch.setattr(ex, "execution", StubExecution(fill_ratio=0.5, price_offset=0.1))
    trade = run(pt.paper_trading_service.open_from_signal(db, _signal(db)))
    assert trade.quantity == pytest.approx(5.0)  # half of 1,000 / 100
    assert trade.paper_entry_price == pytest.approx(100.1)


def test_no_fill_means_no_trade(db, monkeypatch):
    monkeypatch.setattr(ex, "execution", StubExecution(fill_ratio=0.0))
    assert run(pt.paper_trading_service.open_from_signal(db, _signal(db))) is None
    assert db.query(models.PaperTrade).count() == 0


def test_exit_without_liquidity_keeps_the_trade_open(db, monkeypatch):
    trade = make_trade(db)
    monkeypatch.setattr(ex, "execution", StubExecution(fill_ratio=0.0))
    trade = tick(db, trade, 99.0, monkeypatch)  # hard stop wants out
    assert trade.status == "OPEN" and trade.quantity == 10


def test_partial_exit_books_the_sold_part_and_keeps_the_rest(db, monkeypatch):
    trade = make_trade(db)
    user = db.query(models.BotAccount).first()
    before = user.portfolio_value
    stub = StubExecution(fill_ratio=0.4)
    monkeypatch.setattr(ex, "execution", stub)
    trade = tick(db, trade, 99.0, monkeypatch)
    db.refresh(user)
    assert trade.status == "OPEN" and trade.quantity == pytest.approx(6.0)
    assert user.portfolio_value < before  # the sold 4 units were a loss
    assert stub.published == [{"BTC-USD": 99.0}]  # the exit quote was published first
