"""Round trip against a running Financial Analytics Dashboard backend.

Skipped unless EXCHANGE_LIVE_URL is set; CI starts the exchange from its repository and sets it.
The exchange must list EXCHANGE_LIVE_EMAIL in MARKET_OPERATOR_EMAILS."""
import asyncio
import os
import uuid

import httpx
import pytest

from app.services.execution import ExchangeExecution

URL = os.environ.get("EXCHANGE_LIVE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="EXCHANGE_LIVE_URL not set")


def test_publish_buy_sell_round_trip_settles_on_the_exchange():
    email = os.environ.get("EXCHANGE_LIVE_EMAIL", "trading-engine@example.com")
    ticker = f"T{uuid.uuid4().hex[:6].upper()}-USD"  # fresh asset, so earlier runs cannot interfere

    async def scenario():
        client = ExchangeExecution(URL, email, "live-test-password-1")
        try:
            await client.publish_prices({ticker: 100.0})
            bought = await client.buy(ticker, 10.0, 100.0)
            sold = await client.sell(ticker, 10.0, 100.0)
            account = (await client._request("GET", "/trading/account")).json()
            return bought, sold, account
        finally:
            await client.close()

    bought, sold, account = asyncio.run(scenario())
    assert bought.quantity == pytest.approx(10.0) and bought.price > 100.0  # paid the ask
    assert sold.quantity == pytest.approx(10.0) and sold.price < 100.0      # received the bid
    assert ticker.removesuffix("-USD") not in account["holdings"]          # flat again
