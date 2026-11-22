from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base

class PaperTrade(Base):
    __tablename__ = "bot_paper_trades"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, ForeignKey("bot_signals.id"))
    user_id = Column(Integer, ForeignKey("bot_accounts.id"))
    ticker = Column(String, index=True, nullable=False)
    paper_entry_price = Column(Float)
    paper_exit_price = Column(Float)
    quantity = Column(Float)  # fractional crypto units
    status = Column(String, default="OPEN") # OPEN, CLOSED
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)
    pnl_percent = Column(Float, default=0.0)
    pnl_dollar = Column(Float, default=0.0)
    max_favorable_excursion = Column(Float, default=0.0)
    max_adverse_excursion = Column(Float, default=0.0)
    exit_reason = Column(String, nullable=True)

    user = relationship("BotAccount", back_populates="trades")
    signal = relationship("Signal", back_populates="paper_trade")
