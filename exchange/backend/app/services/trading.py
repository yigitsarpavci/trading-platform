"""Simulated exchange: a limit-order book with price-time priority, settlement and a market maker.

Flow of an order (`place_order`):
1. lock the asset row, so orders on one asset are matched one at a time;
2. pre-trade check: a buy needs free cash, a sell needs free holdings (open orders reserve both);
3. match against the book at the resting (maker) price, oldest first at each price level;
4. settle every fill: move cash between the two users and update both trading portfolios;
5. an IOC order cancels its unfilled remainder, a GTC order leaves it on the book.

Reference prices published by a market operator (e.g. the trading engine) make the built-in
market maker re-quote a bid and an ask around them, so there is always liquidity to trade against.
"""
import secrets
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import settings
from app.models.all_models import (
    Asset,
    Order,
    OrderSide,
    OrderStatus,
    Portfolio,
    PortfolioHolding,
    TimeInForce,
    Trade,
    User,
)

EPS = 1e-9
MARKET_MAKER_START_CASH = 10_000_000.0

Fill = Tuple[Trade, Order, Order]  # (trade, buy order, sell order)


class OrderRejected(ValueError):
    """Raised when an order fails validation or the pre-trade check."""


class OrderNotFound(LookupError):
    pass


# --------------------------------------------------------------------------- balances


def trading_portfolio(db: Session, user_id: int) -> Portfolio:
    """The portfolio exchange fills settle into: the user's first one, created on demand."""
    portfolio = (
        db.query(Portfolio).filter(Portfolio.user_id == user_id).order_by(Portfolio.id.asc()).first()
    )
    if portfolio is None:
        portfolio = Portfolio(user_id=user_id, name="Trading")
        db.add(portfolio)
        db.flush()
    return portfolio


def _holding(db: Session, portfolio_id: int, asset_id: int) -> Optional[PortfolioHolding]:
    return (
        db.query(PortfolioHolding)
        .filter(PortfolioHolding.portfolio_id == portfolio_id, PortfolioHolding.asset_id == asset_id)
        .first()
    )


def held_quantity(db: Session, user_id: int, asset_id: int) -> float:
    holding = _holding(db, trading_portfolio(db, user_id).id, asset_id)
    return holding.quantity if holding else 0.0


def reserved_cash(db: Session, user_id: int) -> float:
    """Cash committed to open buy orders (valued at their limit price, an upper bound)."""
    total = (
        db.query(func.sum((Order.quantity - Order.filled_quantity) * Order.price))
        .filter(Order.user_id == user_id, Order.side == OrderSide.BUY, Order.status == OrderStatus.OPEN)
        .scalar()
    )
    return float(total or 0.0)


def reserved_quantity(db: Session, user_id: int, asset_id: int) -> float:
    total = (
        db.query(func.sum(Order.quantity - Order.filled_quantity))
        .filter(
            Order.user_id == user_id,
            Order.asset_id == asset_id,
            Order.side == OrderSide.SELL,
            Order.status == OrderStatus.OPEN,
        )
        .scalar()
    )
    return float(total or 0.0)


def _check_funds(db: Session, user: User, asset: Asset, side: OrderSide, price: float, quantity: float) -> None:
    if side == OrderSide.BUY:
        needed = price * quantity
        available = user.cash_balance - reserved_cash(db, user.id)
        if needed > available + EPS:
            raise OrderRejected(f"Insufficient cash: the order needs {needed:,.2f}, {available:,.2f} is available")
    else:
        available = held_quantity(db, user.id, asset.id) - reserved_quantity(db, user.id, asset.id)
        if quantity > available + EPS:
            raise OrderRejected(
                f"Insufficient {asset.ticker_symbol}: the order sells {quantity:g}, {max(available, 0):g} is available"
            )


def _recompute_allocations(db: Session, portfolio_id: int) -> None:
    holdings = db.query(PortfolioHolding).filter(PortfolioHolding.portfolio_id == portfolio_id).all()
    total = sum(h.quantity * h.average_buy_price for h in holdings)
    for h in holdings:
        h.allocation_percentage = (h.quantity * h.average_buy_price / total * 100.0) if total > 0 else 0.0


def _settle(db: Session, trade: Trade, buy_order: Order, sell_order: Order) -> None:
    """Move cash from buyer to seller and the asset from seller to buyer."""
    notional = trade.price * trade.quantity
    buyer = db.get(User, buy_order.user_id)
    seller = db.get(User, sell_order.user_id)
    buyer.cash_balance -= notional
    seller.cash_balance += notional

    buyer_pf = trading_portfolio(db, buyer.id)
    bought = _holding(db, buyer_pf.id, trade.asset_id)
    if bought is None:
        bought = PortfolioHolding(
            portfolio_id=buyer_pf.id, asset_id=trade.asset_id, quantity=0.0,
            average_buy_price=trade.price, allocation_percentage=0.0,
        )
        db.add(bought)
    new_qty = bought.quantity + trade.quantity
    bought.average_buy_price = (bought.quantity * bought.average_buy_price + notional) / new_qty
    bought.quantity = new_qty

    seller_pf = trading_portfolio(db, seller.id)
    sold = _holding(db, seller_pf.id, trade.asset_id)
    if sold is not None:
        sold.quantity = max(0.0, sold.quantity - trade.quantity)
        if sold.quantity <= EPS:
            db.delete(sold)

    db.flush()
    _recompute_allocations(db, buyer_pf.id)
    if seller_pf.id != buyer_pf.id:
        _recompute_allocations(db, seller_pf.id)


# --------------------------------------------------------------------------- matching


def _match_order(db: Session, order: Order) -> List[Fill]:
    """Match `order` against the book (price-time priority, maker price). Does not commit."""
    fills: List[Fill] = []
    if order.status != OrderStatus.OPEN:
        return fills

    remaining_qty = order.quantity - order.filled_quantity
    while remaining_qty > EPS:
        if order.side == OrderSide.BUY:
            # Cheapest sell at or below our limit, oldest first; never our own orders.
            opposite_order = db.query(Order).filter(
                Order.asset_id == order.asset_id,
                Order.side == OrderSide.SELL,
                Order.status == OrderStatus.OPEN,
                Order.price <= order.price,
                Order.user_id != order.user_id,
            ).order_by(Order.price.asc(), Order.created_at.asc(), Order.id.asc()).first()
        else:
            # Highest buy at or above our limit, oldest first; never our own orders.
            opposite_order = db.query(Order).filter(
                Order.asset_id == order.asset_id,
                Order.side == OrderSide.BUY,
                Order.status == OrderStatus.OPEN,
                Order.price >= order.price,
                Order.user_id != order.user_id,
            ).order_by(Order.price.desc(), Order.created_at.asc(), Order.id.asc()).first()

        if not opposite_order:
            break

        opposite_remaining = opposite_order.quantity - opposite_order.filled_quantity
        if opposite_remaining <= EPS:
            # Filled in memory but not yet flushed: mark it so the next query skips it.
            opposite_order.status = OrderStatus.FILLED
            db.flush()
            continue
        trade_qty = min(remaining_qty, opposite_remaining)
        execution_price = opposite_order.price  # the resting (maker) order sets the price

        order.filled_quantity += trade_qty
        opposite_order.filled_quantity += trade_qty
        remaining_qty -= trade_qty

        if order.filled_quantity >= order.quantity - EPS:
            order.status = OrderStatus.FILLED
        if opposite_order.filled_quantity >= opposite_order.quantity - EPS:
            opposite_order.status = OrderStatus.FILLED

        buy_order, sell_order = (order, opposite_order) if order.side == OrderSide.BUY else (opposite_order, order)
        trade = Trade(
            buy_order_id=buy_order.id,
            sell_order_id=sell_order.id,
            asset_id=order.asset_id,
            price=execution_price,
            quantity=trade_qty,
        )
        db.add(trade)
        fills.append((trade, buy_order, sell_order))
        db.flush()  # make the new fill state visible to the next query, whatever the session's autoflush

    return fills


def _lock_asset(db: Session, asset_id: int) -> Asset:
    # SELECT ... FOR UPDATE on PostgreSQL serializes matching per asset (a no-op on SQLite,
    # which already serializes writers).
    asset = db.query(Asset).filter(Asset.id == asset_id).with_for_update().first()
    if asset is None:
        raise OrderRejected("Asset not found")
    return asset


def _submit(
    db: Session, user: User, asset: Asset, side: OrderSide, price: float, quantity: float,
    time_in_force: TimeInForce,
) -> Tuple[Order, List[Fill]]:
    """Check, record, match and settle one order. The caller holds the asset lock and commits."""
    if price <= 0 or quantity <= 0:
        raise OrderRejected("Price and quantity must be positive")
    _check_funds(db, user, asset, side, price, quantity)

    order = Order(
        user_id=user.id, asset_id=asset.id, side=side, price=price, quantity=quantity,
        filled_quantity=0.0, status=OrderStatus.OPEN, time_in_force=time_in_force,
    )
    db.add(order)
    db.flush()

    fills = _match_order(db, order)
    db.flush()
    for trade, buy_order, sell_order in fills:
        _settle(db, trade, buy_order, sell_order)

    if order.status == OrderStatus.OPEN and time_in_force == TimeInForce.IOC:
        order.status = OrderStatus.CANCELED
    return order, fills


def _vwap(fills: Iterable[Fill]) -> Optional[float]:
    qty = sum(t.quantity for t, _, _ in fills)
    return sum(t.price * t.quantity for t, _, _ in fills) / qty if qty > EPS else None


def place_order(
    db: Session, user_id: int, asset_id: int, side: OrderSide, price: float, quantity: float,
    time_in_force: TimeInForce = TimeInForce.GTC,
) -> Order:
    """Place an order in one transaction; raises OrderRejected (nothing is stored) on a failed check."""
    try:
        asset = _lock_asset(db, asset_id)
        user = db.query(User).filter(User.id == user_id).with_for_update().first()
        if user is None:
            raise OrderRejected("User not found")
        order, fills = _submit(db, user, asset, side, price, quantity, time_in_force)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(order)
    order.avg_fill_price = _vwap(fills)
    order.ticker_symbol = asset.ticker_symbol
    return order


def cancel_order(db: Session, user_id: int, order_id: int) -> Order:
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user_id).with_for_update().first()
    if order is None:
        raise OrderNotFound("Order not found")
    if order.status != OrderStatus.OPEN:
        raise OrderRejected(f"Only open orders can be canceled (this one is {order.status.value})")
    order.status = OrderStatus.CANCELED
    db.commit()
    db.refresh(order)
    return order


def get_order_book(db: Session, asset_id: int):
    bids = db.query(Order.price, func.sum(Order.quantity - Order.filled_quantity).label("total_qty")).filter(
        Order.asset_id == asset_id,
        Order.side == OrderSide.BUY,
        Order.status == OrderStatus.OPEN
    ).group_by(Order.price).order_by(Order.price.desc()).all()

    asks = db.query(Order.price, func.sum(Order.quantity - Order.filled_quantity).label("total_qty")).filter(
        Order.asset_id == asset_id,
        Order.side == OrderSide.SELL,
        Order.status == OrderStatus.OPEN
    ).group_by(Order.price).order_by(Order.price.asc()).all()

    return {
        "bids": [{"price": float(b[0]), "quantity": float(b[1])} for b in bids],
        "asks": [{"price": float(a[0]), "quantity": float(a[1])} for a in asks]
    }


def account_summary(db: Session, user: User) -> dict:
    portfolio = trading_portfolio(db, user.id)
    holdings = (
        db.query(PortfolioHolding, Asset)
        .join(Asset, PortfolioHolding.asset_id == Asset.id)
        .filter(PortfolioHolding.portfolio_id == portfolio.id)
        .all()
    )
    return {
        "cash_balance": user.cash_balance,
        "reserved_cash": reserved_cash(db, user.id),
        "holdings": {asset.ticker_symbol: h.quantity for h, asset in holdings},
    }


# --------------------------------------------------------------------------- market maker


def ensure_market_maker(db: Session) -> User:
    """The liquidity account. It cannot sign in (random password) and starts with ample cash."""
    email = settings.MARKET_MAKER_EMAIL.lower()
    maker = db.query(User).filter(User.email == email).first()
    if maker is None:
        maker = User(
            email=email,
            hashed_password=security.get_password_hash(secrets.token_urlsafe(32)),
            cash_balance=MARKET_MAKER_START_CASH,
        )
        db.add(maker)
        db.flush()
    return maker


def _requote(db: Session, maker: User, asset: Asset) -> None:
    """Replace the maker's quotes on `asset` with a fresh bid and ask around the reference price."""
    for stale in db.query(Order).filter(
        Order.user_id == maker.id, Order.asset_id == asset.id, Order.status == OrderStatus.OPEN
    ).all():
        stale.status = OrderStatus.CANCELED
    db.flush()

    price = asset.reference_price
    half_spread = settings.MARKET_MAKER_SPREAD_BPS / 2 / 10_000
    bid = round(price * (1 - half_spread), 8)
    ask = round(price * (1 + half_spread), 8)
    size = round(settings.MARKET_MAKER_QUOTE_NOTIONAL / price, 8)

    # Simplification: the maker has an unlimited balance sheet. It is topped up so it can always
    # quote both sides; its cash and inventory are not meant to be read as P&L.
    if maker.cash_balance - reserved_cash(db, maker.id) < bid * size:
        maker.cash_balance += MARKET_MAKER_START_CASH
    inventory = held_quantity(db, maker.id, asset.id)
    if inventory < size:
        portfolio = trading_portfolio(db, maker.id)
        holding = _holding(db, portfolio.id, asset.id)
        if holding is None:
            holding = PortfolioHolding(
                portfolio_id=portfolio.id, asset_id=asset.id, quantity=0.0,
                average_buy_price=price, allocation_percentage=0.0,
            )
            db.add(holding)
        holding.quantity += 10 * size
        db.flush()

    _submit(db, maker, asset, OrderSide.BUY, bid, size, TimeInForce.GTC)
    _submit(db, maker, asset, OrderSide.SELL, ask, size, TimeInForce.GTC)


def publish_reference_prices(db: Session, prices: Iterable[Tuple[str, float]]) -> List[Asset]:
    """Store reference prices (creating unknown tickers as Crypto assets) and re-quote the maker."""
    try:
        maker = ensure_market_maker(db)
        now = datetime.now(timezone.utc)
        updated: List[Asset] = []
        for ticker, price in prices:
            ticker = ticker.strip().upper()
            if price <= 0:
                raise OrderRejected(f"Price for {ticker} must be positive")
            asset = db.query(Asset).filter(Asset.ticker_symbol == ticker).with_for_update().first()
            if asset is None:
                asset = Asset(ticker_symbol=ticker, name=ticker, asset_class="Crypto")
                db.add(asset)
                db.flush()
            asset.reference_price = float(price)
            asset.reference_price_at = now
            _requote(db, maker, asset)
            updated.append(asset)
        db.commit()
    except Exception:
        db.rollback()
        raise
    for asset in updated:
        db.refresh(asset)
    return updated
