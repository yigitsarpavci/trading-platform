from typing import Any, Dict
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.bot import models, schemas
from app.api.deps import get_db

from app.api.deps import get_current_user

router = APIRouter()

@router.get("/portfolio", response_model=Dict[str, Any])
def get_portfolio_status(db: Session = Depends(get_db)) -> Any:
    """
    Get current portfolio status (balance, unrealized PnL, net liquidity).
    """
    user = db.query(models.BotAccount).filter(models.BotAccount.id == 1).first()
    if not user:
        user = models.BotAccount(email="demo@alphatrigger.ai")
        db.add(user)
        db.commit()
        db.refresh(user)
        
    # Calculate unrealized PnL from open trades
    open_trades = db.query(models.PaperTrade).filter(models.PaperTrade.status == "OPEN").all()
    unrealized_pnl = sum([t.pnl_dollar for t in open_trades])
    
    return {
        "portfolio_value": user.portfolio_value, # Realized balance
        "unrealized_pnl": round(unrealized_pnl, 2),
        "net_liquidity": round(user.portfolio_value + unrealized_pnl, 2),
        "risk_profile": user.risk_profile,
        "active_positions_count": len(open_trades)
    }

@router.post("/portfolio/reset", dependencies=[Depends(get_current_user)])
def reset_portfolio(data: Dict[str, Any], db: Session = Depends(get_db)):
    """
    Reset portfolio value and clear all trades.
    """
    user = db.query(models.BotAccount).filter(models.BotAccount.id == 1).first()
    if user:
        user.portfolio_value = data.get("value", 10000000.0)
        db.add(user)
        
        # Close any open trades so the new engine starts fresh, but KEEP history
        open_trades = db.query(models.PaperTrade).filter(models.PaperTrade.status == "OPEN").all()
        for t in open_trades:
            t.status = "CLOSED_TIMEOUT"
        
        db.commit()
    return {"status": "success", "new_balance": user.portfolio_value if user else 0}

