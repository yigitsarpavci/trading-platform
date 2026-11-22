"""Where paper trades are filled.

* ``SimulatedExecution`` (default) fills instantly at the quoted price plus random slippage.
* ``ExchangeExecution`` routes every entry and exit as an immediate-or-cancel limit order to the
  Financial Analytics Dashboard's matching engine (https://github.com/yigitsarpavci/financial-analytics-dashboard).
  The engine also publishes its prices there each cycle as reference prices, which makes the
  exchange's market maker quote a bid and an ask around them; fills then come from a real order
  book with a real spread, partial fills and pre-trade cash/holding checks.
"""
import logging
import random
from dataclasses import dataclass
from typing import Dict, Optional

import httpx

from app.core.config import settings
from app.services.settings_service import settings_service

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

    async def close(self) -> None:
        return None


class ExchangeError(RuntimeError):
    pass


def exchange_symbol(ticker: str) -> str:
    """Engine tickers are quote-currency pairs (BTC-USD); the exchange lists the base asset (BTC)."""
    t = ticker.strip().upper()
    return t[:-4] if t.endswith("-USD") else t


class ExchangeExecution:
    """Client for the exchange's REST API. Signs in with its own account (registering it on first
    use) and re-authenticates once when a token is rejected."""

    mode = "exchange"

    def __init__(self, base_url: str, email: str, password: str, tolerance_bps: float = 20.0,
                 client: Optional[httpx.AsyncClient] = None):
        if not password:
            raise ValueError("EXCHANGE_PASSWORD must be set when EXECUTION_MODE=exchange")
        self.email = email
        self.password = password
        self.tolerance = tolerance_bps / 10_000
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/") + "/api/v1", timeout=5.0)
        self._token: Optional[str] = None
        self._asset_ids: Dict[str, int] = {}

    # -------------------------------------------------------------- auth

    async def _login(self) -> None:
        res = await self._client.post("/auth/login", data={"username": self.email, "password": self.password})
        if res.status_code == 400:  # unknown account: create it once, then sign in
            reg = await self._client.post("/auth/register", json={"email": self.email, "password": self.password})
            if reg.status_code not in (200, 201):
                raise ExchangeError(f"Could not register {self.email}: {reg.status_code} {reg.text}")
            res = await self._client.post("/auth/login", data={"username": self.email, "password": self.password})
        if res.status_code != 200:
            raise ExchangeError(f"Exchange login failed: {res.status_code} {res.text}")
        self._token = res.json()["access_token"]

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if self._token is None:
            await self._login()
        for attempt in (1, 2):
            res = await self._client.request(method, path, headers={"Authorization": f"Bearer {self._token}"}, **kwargs)
            if res.status_code in (401, 403) and attempt == 1 and "operator" not in res.text.lower():
                await self._login()  # expired or revoked token
                continue
            return res
        return res

    # -------------------------------------------------------------- market data

    async def publish_prices(self, prices: Dict[str, float]) -> None:
        body = {"prices": [{"ticker_symbol": exchange_symbol(t), "price": p} for t, p in prices.items() if p > 0]}
        if not body["prices"]:
            return
        res = await self._request("PUT", "/market/prices", json=body)
        if res.status_code != 200:
            raise ExchangeError(f"Publishing prices failed: {res.status_code} {res.text}")
        for item in res.json():
            self._asset_ids[item["ticker_symbol"]] = item["asset_id"]

    async def _asset_id(self, ticker: str) -> int:
        symbol = exchange_symbol(ticker)
        if symbol not in self._asset_ids:
            res = await self._client.get("/market/prices")
            res.raise_for_status()
            self._asset_ids.update({i["ticker_symbol"]: i["asset_id"] for i in res.json()})
        if symbol not in self._asset_ids:
            raise ExchangeError(f"{symbol} has no reference price on the exchange yet")
        return self._asset_ids[symbol]

    # -------------------------------------------------------------- orders

    async def _ioc(self, ticker: str, side: str, quantity: float, limit: float) -> Optional[Fill]:
        body = {
            "asset_id": await self._asset_id(ticker),
            "side": side,
            "price": round(limit, 8),
            "quantity": round(quantity, 8),
            "time_in_force": "IOC",
        }
        res = await self._request("POST", "/trading/orders", json=body)
        if res.status_code == 400:  # failed pre-trade check (cash or holdings)
            log.warning("Exchange rejected %s %s: %s", side, ticker, res.json().get("detail"))
            return None
        if res.status_code != 200:
            raise ExchangeError(f"Order failed: {res.status_code} {res.text}")
        order = res.json()
        if not order.get("filled_quantity") or order.get("avg_fill_price") is None:
            return None
        return Fill(float(order["filled_quantity"]), float(order["avg_fill_price"]))

    async def buy(self, ticker: str, quantity: float, price: float) -> Optional[Fill]:
        """Buy up to `quantity`, paying at most `price` plus the tolerance."""
        return await self._ioc(ticker, "BUY", quantity, price * (1 + self.tolerance))

    async def sell(self, ticker: str, quantity: float, price: float) -> Optional[Fill]:
        """Sell up to `quantity`, accepting at least `price` minus the tolerance."""
        return await self._ioc(ticker, "SELL", quantity, price * (1 - self.tolerance))

    async def close(self) -> None:
        await self._client.aclose()


def build_execution():
    if settings.EXECUTION_MODE.lower() == "exchange":
        return ExchangeExecution(
            settings.EXCHANGE_URL, settings.EXCHANGE_EMAIL, settings.EXCHANGE_PASSWORD,
            settings.EXCHANGE_PRICE_TOLERANCE_BPS,
        )
    return SimulatedExecution()


execution = build_execution()
