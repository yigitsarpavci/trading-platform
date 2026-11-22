"""Exchange execution: the HTTP client (against a fake exchange) and how the engine handles
missing, partial and full fills."""
import asyncio
import json

import httpx
import pytest

from app import models
from app.services import execution as ex
from app.services import paper_trading as pt
from tests.test_paper_trading import db, make_trade, run, tick  # noqa: F401  (fixtures and helpers)


# ------------------------------------------------------------------ fake exchange


class FakeExchange:
    """Implements the handful of endpoints the client uses."""

    def __init__(self, fill_ratio=1.0, reject=False):
        self.users = {}
        self.calls = []
        self.fill_ratio = fill_ratio
        self.reject = reject
        self.expire_next_token = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        self.calls.append((request.method, path))
        if path == "/auth/login":
            form = dict(x.split("=") for x in request.content.decode().split("&"))
            email = form["username"].replace("%40", "@")
            if self.users.get(email) != form["password"]:
                return httpx.Response(400, json={"detail": "Incorrect email or password"})
            return httpx.Response(200, json={"access_token": f"token-{len(self.calls)}", "token_type": "bearer"})
        if path == "/auth/register":
            body = json.loads(request.content)
            self.users[body["email"]] = body["password"]
            return httpx.Response(200, json={"id": 1, "email": body["email"]})
        if self.expire_next_token:
            self.expire_next_token = False
            return httpx.Response(403, json={"detail": "Could not validate credentials"})
        if path == "/market/prices" and request.method == "PUT":
            prices = json.loads(request.content)["prices"]
            return httpx.Response(200, json=[
                {"asset_id": i + 1, "ticker_symbol": p["ticker_symbol"], "reference_price": p["price"]}
                for i, p in enumerate(prices)
            ])
        if path == "/market/prices":
            return httpx.Response(200, json=[{"asset_id": 1, "ticker_symbol": "BTC", "reference_price": 100.0}])
        if path == "/trading/orders":
            body = json.loads(request.content)
            if self.reject:
                return httpx.Response(400, json={"detail": "Insufficient cash"})
            filled = body["quantity"] * self.fill_ratio
            return httpx.Response(200, json={
                **body, "id": 7, "filled_quantity": filled,
                "avg_fill_price": body["price"] if filled else None,
                "status": "FILLED" if self.fill_ratio == 1 else "CANCELED",
            })
        return httpx.Response(404)


def client_for(fake: FakeExchange, tolerance_bps=20.0) -> ex.ExchangeExecution:
    transport = httpx.MockTransport(fake.handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://exchange/api/v1")
    return ex.ExchangeExecution("http://exchange", "engine@x.io", "pw", tolerance_bps, client=http)


def test_symbols_drop_the_quote_currency():
    assert ex.exchange_symbol("btc-usd") == "BTC"
    assert ex.exchange_symbol("AAPL") == "AAPL"


def test_password_is_required():
    with pytest.raises(ValueError):
        ex.ExchangeExecution("http://exchange", "engine@x.io", "")


def test_registers_once_then_publishes_and_caches_asset_ids():
    fake = FakeExchange()
    client = client_for(fake)
    asyncio.run(client.publish_prices({"BTC-USD": 100.0, "ETH-USD": 0.0}))
    assert ("POST", "/auth/register") in fake.calls
    assert client._asset_ids == {"BTC": 1}  # non-positive prices are not published


def test_buy_is_an_ioc_limit_within_the_tolerance():
    fake = FakeExchange()
    client = client_for(fake, tolerance_bps=20)
    asyncio.run(client.publish_prices({"BTC-USD": 100.0}))
    fill = asyncio.run(client.buy("BTC-USD", 2.0, 100.0))
    assert fill == ex.Fill(2.0, pytest.approx(100.2))
    sell = asyncio.run(client.sell("BTC-USD", 2.0, 100.0))
    assert sell.price == pytest.approx(99.8)


def test_rejection_and_empty_fill_return_none():
    assert asyncio.run(client_for(FakeExchange(reject=True)).buy("BTC-USD", 1.0, 100.0)) is None
    assert asyncio.run(client_for(FakeExchange(fill_ratio=0.0)).buy("BTC-USD", 1.0, 100.0)) is None


def test_expired_token_triggers_one_relogin():
    fake = FakeExchange()
    client = client_for(fake)
    asyncio.run(client.publish_prices({"BTC-USD": 100.0}))
    fake.expire_next_token = True
    asyncio.run(client.publish_prices({"BTC-USD": 101.0}))
    assert [c for c in fake.calls if c[1] == "/auth/login"].__len__() >= 3  # first, after register, after expiry


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
    user = models.User(email="e@x.io", portfolio_value=100_000.0)
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
    user = db.query(models.User).first()
    before = user.portfolio_value
    stub = StubExecution(fill_ratio=0.4)
    monkeypatch.setattr(ex, "execution", stub)
    trade = tick(db, trade, 99.0, monkeypatch)
    db.refresh(user)
    assert trade.status == "OPEN" and trade.quantity == pytest.approx(6.0)
    assert user.portfolio_value < before  # the sold 4 units were a loss
    assert stub.published == [{"BTC-USD": 99.0}]  # the exit quote was published first
