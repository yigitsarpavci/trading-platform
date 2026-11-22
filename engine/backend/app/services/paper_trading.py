from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app import models
from app.services.market_data import market_data
from app.services.settings_service import settings_service
from app.services import execution as execution_module
from datetime import datetime, timezone


class PaperTradingService:
    """
    Paper trading service V7 with improved exit logic.
    
    Key changes:
    - Trailing stop only activates after MFE > 1.5% (was 0.2%)
    - Break-even stop: move SL to entry after +0.5% MFE
    - Timeout extended to 60s (was 20s) — let winners breathe
    - Removed "only close trailing if net pnl > 0" check
    """

    # Upper bound on a single position, whatever the stop distance (a very tight stop would
    # otherwise imply an enormous notional).
    MAX_POSITION_FRACTION = 0.20

    @staticmethod
    def _position_notional(signal: models.Signal, portfolio_value: float, fallback_fraction: float) -> float:
        """Notional to deploy for a signal.

        The engine attaches a risk-normalized notional to each signal (fixed dollar risk divided by
        the volatility-derived stop distance), so quieter markets get larger positions and volatile
        ones smaller. Signals without a usable figure fall back to a fixed fraction of the portfolio.
        """
        try:
            suggested = float(signal.suggested_amount)
        except (TypeError, ValueError):
            suggested = 0.0
        notional = suggested if suggested > 0 else portfolio_value * fallback_fraction
        return min(notional, portfolio_value * PaperTradingService.MAX_POSITION_FRACTION)

    @staticmethod
    def _realize_partial_exit(db: Session, trade: models.PaperTrade, fill, conf) -> None:
        """Book the P&L of the part that was sold and keep the rest of the position open."""
        direction = -1.0 if trade.signal and trade.signal.signal_type == "SELL" else 1.0
        raw = direction * (fill.price - trade.paper_entry_price) / trade.paper_entry_price
        pnl = raw * trade.paper_entry_price * fill.quantity * conf.leverage - fill.price * fill.quantity * conf.commission_rate
        user = db.query(models.User).filter(models.User.id == trade.user_id).first()
        if user:
            user.portfolio_value += pnl
            db.add(user)
        trade.quantity = round(trade.quantity - fill.quantity, 8)
        db.add(trade)

    async def open_from_signal(self, db: Session, signal: models.Signal) -> models.PaperTrade:
        """Open a paper trade from a signal with realistic execution costs."""
        conf = settings_service.get_settings()

        # Prevent duplicate open positions
        existing = db.query(models.PaperTrade).filter(
            models.PaperTrade.ticker == signal.ticker,
            models.PaperTrade.status.in_(["OPEN", "PENDING_TRIGGER"])
        ).first()
        if existing:
            return existing

        # Dynamic position sizing: risk_per_trade % of portfolio
        user = db.query(models.User).filter(models.User.id == signal.user_id).first()
        portfolio_value = user.portfolio_value if user else 10_000_000.0

        if signal.entry_price <= 0:
            return None  # Safety guard

        position_dollars = self._position_notional(signal, portfolio_value, conf.risk_per_trade)
        quantity = round(position_dollars / signal.entry_price, 8)
        if quantity <= 0:
            return None

        # Fill: simulated slippage, or an IOC order on the exchange (which may fill partly or not at all)
        execution = execution_module.execution
        try:
            if signal.signal_type == "SELL":
                fill = await execution.sell(signal.ticker, quantity, signal.entry_price)
            else:
                fill = await execution.buy(signal.ticker, quantity, signal.entry_price)
        except Exception as exc:  # exchange unreachable: skip this signal, keep the loop alive
            print(f"Entry not executed for {signal.ticker}: {exc}")
            return None
        if fill is None or fill.quantity <= 0:
            return None
        quantity = round(fill.quantity, 8)
        actual_entry = fill.price

        # Entry commission
        entry_fee = actual_entry * quantity * conf.commission_rate
        if user:
            user.portfolio_value -= entry_fee
            db.add(user)

        trade = models.PaperTrade(
            signal_id=signal.id,
            user_id=signal.user_id,
            ticker=signal.ticker,
            paper_entry_price=round(actual_entry, 6),
            quantity=quantity,
            status="OPEN",
            opened_at=datetime.now(timezone.utc),
            pnl_percent=0.0,
            pnl_dollar=round(-entry_fee, 2),
            max_favorable_excursion=0.0,
            max_adverse_excursion=0.0
        )
        db.add(trade)
        db.commit()
        db.refresh(trade)
        return trade

    async def update_all_trades(self, db: Session):
        """Update all open trades and broadcast portfolio status."""
        open_trades = db.query(models.PaperTrade).filter(
            models.PaperTrade.status.in_(["OPEN", "PENDING_TRIGGER"])
        ).all()

        for trade in open_trades:
            try:
                await self._update_single_trade(db, trade)
            except Exception as e:
                print(f"Error updating trade {trade.id} ({trade.ticker}): {e}")

        # Broadcast portfolio snapshot
        user = db.query(models.User).filter(models.User.id == 1).first()
        if user:
            current_open = db.query(models.PaperTrade).filter(
                models.PaperTrade.status == "OPEN"
            ).all()
            unrealized = sum(t.pnl_dollar or 0.0 for t in current_open)

            from app.api.api_v1.endpoints.ws import manager
            import asyncio
            asyncio.create_task(manager.broadcast({
                "type": "PORTFOLIO_UPDATE",
                "payload": {
                    "portfolio_value": round(user.portfolio_value, 2),
                    "unrealized_pnl": round(unrealized, 2),
                    "net_liquidity": round(user.portfolio_value + unrealized, 2),
                    "active_positions": len(current_open)
                }
            }))

    async def _update_single_trade(self, db: Session, trade: models.PaperTrade):
        """Update a single trade's PnL and check exit conditions — V7 logic."""
        conf = settings_service.get_settings()

        quote = await market_data.get_quote(trade.ticker)
        if "error" in quote:
            return

        current_price = quote.get("price")
        if not isinstance(current_price, (int, float)) or current_price <= 0:
            return

        signal = trade.signal
        if not signal or not trade.paper_entry_price or trade.paper_entry_price <= 0:
            return

        if trade.status != "OPEN":
            return

        # === Calculate Net Leveraged PnL ===
        if signal.signal_type == "SELL":
            est_exit_slippage = 1.0 + (conf.slippage_max / 2)
            est_actual_exit = current_price * est_exit_slippage
            raw_net_pnl = (trade.paper_entry_price - est_actual_exit) / trade.paper_entry_price
        else:
            est_exit_slippage = 1.0 - (conf.slippage_max / 2)
            est_actual_exit = current_price * est_exit_slippage
            raw_net_pnl = (est_actual_exit - trade.paper_entry_price) / trade.paper_entry_price
            
        est_exit_fee = est_actual_exit * trade.quantity * conf.commission_rate
        entry_fee = trade.paper_entry_price * trade.quantity * conf.commission_rate

        net_pnl_dollar = (raw_net_pnl * trade.paper_entry_price * trade.quantity * conf.leverage) - (est_exit_fee + entry_fee)
        margin_used = (trade.paper_entry_price * trade.quantity) / conf.leverage
        net_pnl_pct = (net_pnl_dollar / margin_used) * 100.0 if margin_used > 0 else 0.0

        trade.pnl_percent = round(net_pnl_pct, 2)
        trade.pnl_dollar = round(net_pnl_dollar, 2)

        leveraged_pnl_pct = net_pnl_pct

        # === Update MFE / MAE ===
        if leveraged_pnl_pct > (trade.max_favorable_excursion or 0.0):
            trade.max_favorable_excursion = leveraged_pnl_pct
        if leveraged_pnl_pct < (trade.max_adverse_excursion or 0.0):
            trade.max_adverse_excursion = leveraged_pnl_pct

        # === V8 EXIT LOGIC (Risk-First State Machine) ===
        exit_reason = None
        new_status = None

        mfe = trade.max_favorable_excursion or 0.0
        r_dist = conf.sl_pct * 100  # 1R in percentage points (e.g. 0.8)
        
        age_seconds = 0
        if trade.opened_at:
            age_seconds = (datetime.now(timezone.utc) - trade.opened_at.replace(tzinfo=timezone.utc)).total_seconds()

        # A. Hard Stop Loss
        if signal.signal_type == "SELL":
            if signal.stop_loss and current_price >= signal.stop_loss:
                new_status = "CLOSED_LOSS"
                exit_reason = "Hard Stop Hit"
        else:
            if signal.stop_loss and current_price <= signal.stop_loss:
                new_status = "CLOSED_LOSS"
                exit_reason = "Hard Stop Hit"

        # B. No-Follow-Through (State 1) - If no movement within 45s, kill it
        if not new_status and age_seconds >= 45 and mfe < 0.10:
            new_status = "CLOSED_LOSS" if leveraged_pnl_pct < 0 else "CLOSED_WIN"
            exit_reason = "NO_IMMEDIATE_FOLLOW_THROUGH"

        # C. Break-Even Stop (State 2) - After +0.5R MFE
        if not new_status and mfe >= (0.5 * r_dist) and leveraged_pnl_pct <= 0:
            new_status = "CLOSED_WIN"
            exit_reason = "Break-Even Stop"

        # D. Trailing Stop (State 3) - After +0.8R MFE
        if not new_status and mfe >= (0.8 * r_dist):
            trailing_buffer = r_dist * 0.4  # Trail by 0.4R
            drawdown_from_peak = mfe - leveraged_pnl_pct
            if drawdown_from_peak > trailing_buffer:
                new_status = "CLOSED_WIN"
                exit_reason = "Trailing Stop"

        # E. Take Profit Target Hit
        if not new_status:
            if signal.signal_type == "SELL":
                if signal.take_profit and current_price <= signal.take_profit:
                    new_status = "CLOSED_WIN"
                    exit_reason = "Target Hit"
            else:
                if signal.take_profit and current_price >= signal.take_profit:
                    new_status = "CLOSED_WIN"
                    exit_reason = "Target Hit"

        # F. Time Stop (State 4) - Max 300 seconds (5 mins)
        if not new_status and age_seconds >= 300:
            new_status = "CLOSED_TIMEOUT"
            exit_reason = "Time Stop"

        # === Execute Close ===
        if new_status:
            execution = execution_module.execution
            try:
                # Exits are priced on a fresh quote: publish it first so the exchange's market
                # maker quotes around the same price (a no-op in simulated mode).
                await execution.publish_prices({trade.ticker: current_price})
                if signal.signal_type == "SELL":
                    fill = await execution.buy(trade.ticker, trade.quantity, current_price)
                else:
                    fill = await execution.sell(trade.ticker, trade.quantity, current_price)
            except Exception as exc:
                print(f"Exit not executed for {trade.ticker}: {exc}")
                fill = None
            if fill is None or fill.quantity <= 0:
                # No liquidity within tolerance: keep the trade open and retry next cycle.
                db.add(trade)
                db.commit()
                return
            if fill.quantity < trade.quantity - 1e-9:
                self._realize_partial_exit(db, trade, fill, conf)
                db.commit()
                return

            actual_exit = fill.price
            exit_fee = actual_exit * trade.quantity * conf.commission_rate

            if signal.signal_type == "SELL":
                final_raw_pnl = (trade.paper_entry_price - actual_exit) / trade.paper_entry_price
            else:
                final_raw_pnl = (actual_exit - trade.paper_entry_price) / trade.paper_entry_price
                
            final_pnl_dollar = (final_raw_pnl * trade.paper_entry_price * trade.quantity * conf.leverage) - exit_fee

            trade.status = new_status
            trade.paper_exit_price = round(actual_exit, 6)
            trade.pnl_dollar = round(final_pnl_dollar, 2)
            trade.closed_at = datetime.now(timezone.utc)
            trade.exit_reason = exit_reason

            # Recalculate pnl_percent from final dollar amount
            notional = trade.paper_entry_price * trade.quantity
            trade.pnl_percent = round((final_pnl_dollar / notional) * 100, 2) if notional > 0 else 0.0

            # Update user portfolio
            user = db.query(models.User).filter(models.User.id == trade.user_id).first()
            if user:
                user.portfolio_value += final_pnl_dollar
                db.add(user)

            # Record outcome for global risk management
            from app.services.bot_state import bot_state_service
            bot_state_service.record_trade_result(final_pnl_dollar, trade.ticker)

        db.add(trade)
        db.commit()


paper_trading_service = PaperTradingService()
