from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.bot import models
from app.bot.services.market_data import PROVIDERS, market_data
from app.bot.services.settings_service import settings_service

router = APIRouter()


def _read() -> Dict[str, Any]:
    return {
        **settings_service.get_settings().model_dump(),
        "market_data_provider": market_data.name,
        "market_data_providers": list(PROVIDERS),
    }


@router.get("/")
def get_settings():
    return _read()


@router.post("/update")
def update_settings(
    changes: Dict[str, Any],
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Update risk settings and/or the market data provider (signed-in users only).

    The provider can only change while the bot holds no position: prices from the synthetic feed
    and from Yahoo Finance are on different scales, so open trades would be re-priced nonsensically."""
    provider = changes.pop("market_data_provider", None)
    if provider is not None and provider != market_data.name:
        if db.query(models.PaperTrade).filter(models.PaperTrade.status == "OPEN").count():
            raise HTTPException(status_code=409, detail="Close or wait for open positions before switching the price source")
        try:
            market_data.set_provider(provider)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    settings_service.update_settings(changes)
    return _read()
