"""Where the bot's trades are filled.

* ``ExchangeExecution`` (default) trades on the platform's own order book, in process: each cycle's
  prices are published as reference prices (the market maker re-quotes around them) and every
  entry and exit is an immediate-or-cancel limit order through the same matching, pre-trade checks
  and settlement as any user's order. Fills come with a real spread and can be partial.
* ``SimulatedExecution`` fills instantly at the quoted price plus random slippage (no exchange).
"""
import logging
import random
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.bot.config import settings
from app.bot.services.settings_service import settings_service

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Fill:
    quantity: float
    price: float


class SimulatedExecution:
    mode = "simulated"

    async def publish_prices(self, prices: Dict[str, float]) -> None:
        return None

    async def buy(self, ticker: str, quantity: float, price: float) -> Optional[Fill]:
        slip = settings_service.get_settings().slippage_max
        return Fill(quantity, price * (1.0 + random.random() * slip))

    async def sell(self, ticker: str, quantity: float, price: float) -> Optional[Fill]:
        slip = settings_service.get_settings().slippage_max
        return Fill(quantity, price * (1.0 - random.random() * slip))


def exchange_symbol(ticker: str) -> str:
    """Bot tickers are quote-currency pairs (BTC-USD); the exchange lists the base asset (BTC)."""
    t = ticker.strip().upper()
    return t[:-4] if t.endswith("-USD") else t


class ExchangeExecution:
    """Trades on the platform's order book through the exchange service functions, each call in
    its own database transaction (so a rejected order never leaves partial state behind)."""

    mode = "exchange"

    def __init__(self, session_factory: Optional[Callable[[], Session]] = None, tolerance_bps: Optional[float] = None):
        if session_factory is None:
            from app.db.session import SessionLocal

            session_factory = SessionLocal
        self._session_factory = session_factory
        self.tolerance = (settings.EXCHANGE_PRICE_TOLERANCE_BPS if tolerance_bps is None else tolerance_bps) / 10_000
        self._bot_user_id: Optional[int] = None

    def _bot_user(self, db: Session) -> int:
        if self._bot_user_id is None:
            from app.bot.seed import ensure_exchange_account

            self._bot_user_id = ensure_exchange_account(db)
        return self._bot_user_id

    async def publish_prices(self, prices: Dict[str, float]) -> None:
        from app.services import trading

        items = [(exchange_symbol(t), float(p)) for t, p in prices.items() if p and p > 0]
        if not items:
            return
        db = self._session_factory()
        try:
            trading.publish_reference_prices(db, items)
        finally:
            db.close()

    async def _ioc(self, ticker: str, side: str, quantity: float, limit: float) -> Optional[Fill]:
        from app.models.all_models import Asset, OrderSide, TimeInForce
        from app.services import trading

        db = self._session_factory()
        try:
            asset = db.query(Asset).filter(Asset.ticker_symbol == exchange_symbol(ticker)).first()
            if asset is None:
                log.warning("%s has no reference price on the exchange yet", ticker)
                return None
            try:
                order = trading.place_order(
                    db, self._bot_user(db), asset.id, OrderSide(side), round(limit, 8), round(quantity, 8),
                    TimeInForce.IOC,
                )
            except trading.OrderRejected as exc:  # failed pre-trade check (cash or holdings)
                log.warning("Exchange rejected %s %s: %s", side, ticker, exc)
                return None
            if not order.filled_quantity or order.avg_fill_price is None:
                return None
            return Fill(float(order.filled_quantity), float(order.avg_fill_price))
        finally:
            db.close()

    async def buy(self, ticker: str, quantity: float, price: float) -> Optional[Fill]:
        """Buy up to `quantity`, paying at most `price` plus the tolerance."""
        return await self._ioc(ticker, "BUY", quantity, price * (1 + self.tolerance))

    async def sell(self, ticker: str, quantity: float, price: float) -> Optional[Fill]:
        """Sell up to `quantity`, accepting at least `price` minus the tolerance."""
        return await self._ioc(ticker, "SELL", quantity, price * (1 - self.tolerance))


def build_execution():
    if settings.EXECUTION_MODE.lower() == "simulated":
        return SimulatedExecution()
    return ExchangeExecution()


execution = build_execution()
