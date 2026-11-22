from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api import deps
from app.models.all_models import Asset, User
from app.schemas.all_schemas import MarketPriceRead, ReferencePriceBatch
from app.services import trading

router = APIRouter()


def _read(asset: Asset) -> MarketPriceRead:
    return MarketPriceRead(
        asset_id=asset.id,
        ticker_symbol=asset.ticker_symbol,
        reference_price=asset.reference_price,
        reference_price_at=asset.reference_price_at,
    )


@router.get("/prices", response_model=List[MarketPriceRead])
def list_prices(db: Session = Depends(deps.get_db)):
    """Reference prices of every asset that has one."""
    assets = db.query(Asset).filter(Asset.reference_price.isnot(None)).order_by(Asset.ticker_symbol).all()
    return [_read(a) for a in assets]


@router.put("/prices", response_model=List[MarketPriceRead])
def publish_prices(
    batch: ReferencePriceBatch,
    db: Session = Depends(deps.get_db),
    _operator: User = Depends(deps.require_market_operator),
):
    """Publish reference prices (market operators only). Unknown tickers are created as Crypto
    assets, and the market maker re-quotes a bid and an ask around each new price."""
    try:
        assets = trading.publish_reference_prices(db, [(p.ticker_symbol, p.price) for p in batch.prices])
    except trading.OrderRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return [_read(a) for a in assets]
