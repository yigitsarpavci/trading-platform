"""Exchange behaviour against a real (in-memory SQLite) database: checks, settlement, IOC, cancel,
self-trade prevention, the market maker, the operator-only price endpoint and the schema upgrade."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.api.api import api_router
from app.core.config import settings
from app.core.security import create_access_token
from app.db.init_db import init_db
from app.models.all_models import (
    Asset, Order, OrderSide, OrderStatus, Portfolio, PortfolioHolding, TimeInForce, Trade, User,
)
from app.services import trading


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()


def make_user(db, email, cash=100_000.0, holdings=None):
    user = User(email=email, hashed_password="x", cash_balance=cash)
    db.add(user)
    db.flush()
    pf = Portfolio(user_id=user.id, name="Main")
    db.add(pf)
    db.flush()
    for asset, qty in (holdings or {}).items():
        db.add(PortfolioHolding(portfolio_id=pf.id, asset_id=asset.id, quantity=qty,
                                average_buy_price=100.0, allocation_percentage=100.0))
    db.commit()
    return user


def make_asset(db, ticker="BTC"):
    asset = Asset(ticker_symbol=ticker, name=ticker, asset_class="Crypto")
    db.add(asset)
    db.commit()
    return asset


def qty_of(db, user, asset):
    return trading.held_quantity(db, user.id, asset.id)


# ------------------------------------------------------------------ pre-trade checks


def test_buy_without_enough_cash_is_rejected_and_nothing_is_stored(db):
    asset = make_asset(db)
    buyer = make_user(db, "b@x.io", cash=1_000.0)
    with pytest.raises(trading.OrderRejected, match="Insufficient cash"):
        trading.place_order(db, buyer.id, asset.id, OrderSide.BUY, 100.0, 11.0)
    assert db.query(Order).count() == 0


def test_open_orders_reserve_cash_and_holdings(db):
    asset = make_asset(db)
    user = make_user(db, "u@x.io", cash=1_000.0, holdings={asset: 5.0})
    trading.place_order(db, user.id, asset.id, OrderSide.BUY, 100.0, 8.0)  # rests, reserves 800
    with pytest.raises(trading.OrderRejected, match="Insufficient cash"):
        trading.place_order(db, user.id, asset.id, OrderSide.BUY, 100.0, 3.0)
    trading.place_order(db, user.id, asset.id, OrderSide.SELL, 500.0, 4.0)  # rests, reserves 4 units
    with pytest.raises(trading.OrderRejected, match="Insufficient BTC"):
        trading.place_order(db, user.id, asset.id, OrderSide.SELL, 500.0, 2.0)


# ------------------------------------------------------------------ matching and settlement


def test_fill_settles_cash_and_holdings_at_the_maker_price(db):
    asset = make_asset(db)
    seller = make_user(db, "s@x.io", cash=0.0, holdings={asset: 10.0})
    buyer = make_user(db, "b@x.io", cash=10_000.0)
    trading.place_order(db, seller.id, asset.id, OrderSide.SELL, 90.0, 4.0)
    order = trading.place_order(db, buyer.id, asset.id, OrderSide.BUY, 100.0, 4.0)

    assert order.status == OrderStatus.FILLED
    assert order.avg_fill_price == pytest.approx(90.0)  # resting order's price
    db.refresh(buyer), db.refresh(seller)
    assert buyer.cash_balance == pytest.approx(10_000 - 360)
    assert seller.cash_balance == pytest.approx(360)
    assert qty_of(db, buyer, asset) == pytest.approx(4.0)
    assert qty_of(db, seller, asset) == pytest.approx(6.0)
    holding = db.query(PortfolioHolding).filter(PortfolioHolding.portfolio_id == trading.trading_portfolio(db, buyer.id).id).one()
    assert holding.average_buy_price == pytest.approx(90.0)
    assert holding.allocation_percentage == pytest.approx(100.0)


def test_selling_everything_removes_the_holding(db):
    asset = make_asset(db)
    seller = make_user(db, "s@x.io", cash=0.0, holdings={asset: 2.0})
    buyer = make_user(db, "b@x.io")
    trading.place_order(db, buyer.id, asset.id, OrderSide.BUY, 50.0, 2.0)
    trading.place_order(db, seller.id, asset.id, OrderSide.SELL, 50.0, 2.0)
    assert qty_of(db, seller, asset) == 0.0
    assert db.query(PortfolioHolding).filter(
        PortfolioHolding.portfolio_id == trading.trading_portfolio(db, seller.id).id).count() == 0


def test_ioc_cancels_the_unfilled_remainder(db):
    asset = make_asset(db)
    seller = make_user(db, "s@x.io", holdings={asset: 3.0})
    buyer = make_user(db, "b@x.io")
    trading.place_order(db, seller.id, asset.id, OrderSide.SELL, 100.0, 3.0)
    order = trading.place_order(db, buyer.id, asset.id, OrderSide.BUY, 100.0, 5.0, TimeInForce.IOC)
    assert order.filled_quantity == pytest.approx(3.0)
    assert order.status == OrderStatus.CANCELED
    assert trading.reserved_cash(db, buyer.id) == 0.0  # nothing left resting


def test_ioc_with_no_liquidity_fills_nothing(db):
    asset = make_asset(db)
    buyer = make_user(db, "b@x.io")
    order = trading.place_order(db, buyer.id, asset.id, OrderSide.BUY, 100.0, 1.0, TimeInForce.IOC)
    assert order.filled_quantity == 0.0 and order.avg_fill_price is None
    assert order.status == OrderStatus.CANCELED


def test_own_resting_orders_are_never_matched(db):
    asset = make_asset(db)
    user = make_user(db, "u@x.io", holdings={asset: 5.0})
    trading.place_order(db, user.id, asset.id, OrderSide.SELL, 100.0, 1.0)
    order = trading.place_order(db, user.id, asset.id, OrderSide.BUY, 100.0, 1.0)
    assert order.filled_quantity == 0.0
    assert db.query(Trade).count() == 0


def test_cancel_only_own_open_orders(db):
    asset = make_asset(db)
    user = make_user(db, "u@x.io")
    other = make_user(db, "o@x.io")
    order = trading.place_order(db, user.id, asset.id, OrderSide.BUY, 10.0, 1.0)
    with pytest.raises(trading.OrderNotFound):
        trading.cancel_order(db, other.id, order.id)
    assert trading.cancel_order(db, user.id, order.id).status == OrderStatus.CANCELED
    with pytest.raises(trading.OrderRejected):
        trading.cancel_order(db, user.id, order.id)


# ------------------------------------------------------------------ market maker


def test_reference_price_creates_the_asset_and_two_sided_quotes(db):
    trading.publish_reference_prices(db, [("eth", 2_000.0)])
    asset = db.query(Asset).filter(Asset.ticker_symbol == "ETH").one()
    assert asset.reference_price == 2_000.0
    book = trading.get_order_book(db, asset.id)
    half = settings.MARKET_MAKER_SPREAD_BPS / 2 / 10_000
    assert book["bids"][0]["price"] == pytest.approx(2_000 * (1 - half))
    assert book["asks"][0]["price"] == pytest.approx(2_000 * (1 + half))
    assert book["asks"][0]["quantity"] == pytest.approx(settings.MARKET_MAKER_QUOTE_NOTIONAL / 2_000)


def test_requote_replaces_the_previous_quotes(db):
    trading.publish_reference_prices(db, [("ETH", 2_000.0)])
    trading.publish_reference_prices(db, [("ETH", 2_100.0)])
    asset = db.query(Asset).filter(Asset.ticker_symbol == "ETH").one()
    book = trading.get_order_book(db, asset.id)
    assert len(book["bids"]) == 1 and len(book["asks"]) == 1
    assert book["bids"][0]["price"] > 2_000


def test_round_trip_against_the_maker_pays_the_spread(db):
    trading.publish_reference_prices(db, [("BTC", 100_000.0)])
    asset = db.query(Asset).filter(Asset.ticker_symbol == "BTC").one()
    bot = make_user(db, "bot@x.io", cash=100_000.0)

    buy = trading.place_order(db, bot.id, asset.id, OrderSide.BUY, 100_200.0, 0.1, TimeInForce.IOC)
    sell = trading.place_order(db, bot.id, asset.id, OrderSide.SELL, 99_800.0, 0.1, TimeInForce.IOC)

    half = settings.MARKET_MAKER_SPREAD_BPS / 2 / 10_000
    assert buy.avg_fill_price == pytest.approx(100_000 * (1 + half))
    assert sell.avg_fill_price == pytest.approx(100_000 * (1 - half))
    db.refresh(bot)
    spread_cost = 0.1 * 100_000 * 2 * half
    assert bot.cash_balance == pytest.approx(100_000 - spread_cost)
    assert qty_of(db, bot, asset) == 0.0


# ------------------------------------------------------------------ HTTP layer


@pytest.fixture()
def client(db, monkeypatch):
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[deps.get_db] = lambda: db
    monkeypatch.setattr(settings, "MARKET_OPERATOR_EMAILS", "engine@x.io")
    return TestClient(app)


def auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_only_operators_can_publish_prices(client, db):
    engine_user = make_user(db, "engine@x.io")
    someone = make_user(db, "someone@x.io")
    body = {"prices": [{"ticker_symbol": "SOL", "price": 150.0}]}
    assert client.put("/api/v1/market/prices", json=body).status_code == 401
    assert client.put("/api/v1/market/prices", json=body, headers=auth(someone)).status_code == 403
    res = client.put("/api/v1/market/prices", json=body, headers=auth(engine_user))
    assert res.status_code == 200 and res.json()[0]["reference_price"] == 150.0
    assert client.get("/api/v1/market/prices").json()[0]["ticker_symbol"] == "SOL"


def test_order_endpoint_returns_fills_and_400_on_failed_checks(client, db):
    trading.publish_reference_prices(db, [("SOL", 100.0)])
    asset = db.query(Asset).filter(Asset.ticker_symbol == "SOL").one()
    user = make_user(db, "u@x.io", cash=1_000.0)
    ok = client.post("/api/v1/trading/orders", headers=auth(user), json={
        "asset_id": asset.id, "side": "BUY", "price": 101.0, "quantity": 2, "time_in_force": "IOC"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "FILLED" and ok.json()["avg_fill_price"] == pytest.approx(100.05)
    poor = client.post("/api/v1/trading/orders", headers=auth(user), json={
        "asset_id": asset.id, "side": "BUY", "price": 101.0, "quantity": 50})
    assert poor.status_code == 400 and "Insufficient cash" in poor.json()["detail"]
    account = client.get("/api/v1/trading/account", headers=auth(user)).json()
    assert account["holdings"] == {"SOL": pytest.approx(2.0)}


# ------------------------------------------------------------------ schema upgrade


def test_init_db_adds_the_new_columns_to_an_older_database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR NOT NULL, hashed_password VARCHAR NOT NULL)"))
        conn.execute(text("CREATE TABLE assets (id INTEGER PRIMARY KEY, ticker_symbol VARCHAR NOT NULL, name VARCHAR NOT NULL, asset_class VARCHAR NOT NULL)"))
        conn.execute(text("INSERT INTO users (id, email, hashed_password) VALUES (1, 'old@x.io', 'x')"))
    init_db(engine)
    cols = {t: {c["name"] for c in inspect(engine).get_columns(t)} for t in ("users", "assets", "orders")}
    assert "cash_balance" in cols["users"]
    assert {"reference_price", "reference_price_at"} <= cols["assets"]
    assert "time_in_force" in cols["orders"]
    with engine.connect() as conn:
        assert conn.execute(text("SELECT cash_balance FROM users WHERE id = 1")).scalar() == 100000
