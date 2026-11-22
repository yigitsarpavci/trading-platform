from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.bot import models, schemas
from app.api.deps import get_db
import json
from app.bot.services.signal_engine import signal_engine

from app.api.deps import get_current_user

router = APIRouter()

@router.get("/", response_model=List[schemas.Signal])
def read_signals(db: Session = Depends(get_db), skip: int = 0, limit: int = 100) -> Any:
    """
    Retrieve signals.
    """
    signals = db.query(models.Signal).order_by(models.Signal.created_at.desc()).offset(skip).limit(limit).all()
    return signals

@router.get("/{ticker}", response_model=schemas.Signal)
def read_signal_by_ticker(ticker: str, db: Session = Depends(get_db)) -> Any:
    """
    Get signal by ticker.
    """
    signal = db.query(models.Signal).filter(models.Signal.ticker == ticker.upper()).first()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal

from app.bot.api.ws import manager

@router.get("/", response_model=List[schemas.Signal])
def read_signals(db: Session = Depends(get_db), skip: int = 0, limit: int = 100) -> Any:
    """
    Retrieve signals.
    """
    signals = db.query(models.Signal).order_by(models.Signal.created_at.desc()).offset(skip).limit(limit).all()
    return signals

@router.post("/generate", dependencies=[Depends(get_current_user)], response_model=schemas.Signal)
async def generate_signal(ticker: str, db: Session = Depends(get_db)) -> Any:
    """
    Generate a signal for a specific ticker.
    """
    signal = await signal_engine.run_for_ticker(ticker, db)
    if not signal:
        raise HTTPException(status_code=400, detail=f"No actionable signal found for {ticker} at this time.")
    
    # Automatically open paper trade
    from app.bot.services.paper_trading import paper_trading_service
    await paper_trading_service.open_from_signal(db, signal)
    
    # Broadcast via WebSocket
    await manager.broadcast({
        "type": "SIGNAL_GENERATED",
        "payload": json.loads(json.dumps(schemas.Signal.model_validate(signal).model_dump(), default=str))
    })
    
    return signal

@router.post("/run-watchlist", dependencies=[Depends(get_current_user)], response_model=List[schemas.Signal])
async def run_watchlist_signals(db: Session = Depends(get_db)) -> Any:
    """
    Scan entire watchlist and generate signals.
    """
    signals = await signal_engine.run_batch(db)
    from app.bot.services.paper_trading import paper_trading_service
    
    for signal in signals:
        await paper_trading_service.open_from_signal(db, signal)
        await manager.broadcast({
            "type": "SIGNAL_GENERATED",
            "payload": json.loads(json.dumps(schemas.Signal.model_validate(signal).model_dump(), default=str))
        })
        
    return signals
