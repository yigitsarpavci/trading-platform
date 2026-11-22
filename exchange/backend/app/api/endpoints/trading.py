from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api import deps
from app.models.all_models import Asset, Order, Trade, User
from app.schemas.all_schemas import AccountRead, OrderCreate, OrderRead, TradeRead
from app.services import trading

router = APIRouter()


@router.post("/orders", response_model=OrderRead)
def create_order(
    order_in: OrderCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Place a limit order. GTC rests on the book; IOC cancels whatever does not fill at once.

    Rejected with 400 when the account lacks free cash (buy) or free holdings (sell)."""
    if not db.query(Asset.id).filter(Asset.id == order_in.asset_id).first():
        raise HTTPException(status_code=404, detail="Asset not found")
    try:
        return trading.place_order(
            db=db,
            user_id=current_user.id,
            asset_id=order_in.asset_id,
            side=order_in.side,
            price=order_in.price,
            quantity=order_in.quantity,
            time_in_force=order_in.time_in_force,
        )
    except trading.OrderRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/orders/{order_id}", response_model=OrderRead)
def cancel_order(
    order_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    try:
        return trading.cancel_order(db, current_user.id, order_id)
    except trading.OrderNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except trading.OrderRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/orders", response_model=List[OrderRead])
def get_user_orders(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    orders = db.query(Order).options(joinedload(Order.asset)).filter(Order.user_id == current_user.id).order_by(Order.created_at.desc()).all()
    for o in orders:
        if o.asset:
            o.ticker_symbol = o.asset.ticker_symbol
    return orders


@router.get("/account", response_model=AccountRead)
def get_account(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """Cash, cash reserved by open buy orders, and holdings in the trading portfolio."""
    return trading.account_summary(db, current_user)


@router.get("/order-book")
def get_order_book(
    asset_id: int,
    db: Session = Depends(deps.get_db)
):
    return trading.get_order_book(db, asset_id)


@router.get("/trades", response_model=List[TradeRead])
def get_user_trades(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    trades = db.query(Trade).options(joinedload(Trade.asset)).join(Order, Trade.buy_order_id == Order.id).filter(
        (Order.user_id == current_user.id) |
        (Trade.sell_order.has(user_id=current_user.id))
    ).order_by(Trade.executed_at.desc()).all()

    for t in trades:
        if t.asset:
            t.ticker_symbol = t.asset.ticker_symbol

    return trades
