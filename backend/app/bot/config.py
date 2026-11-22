from pydantic_settings import BaseSettings


class BotSettings(BaseSettings):
    """Settings of the trading bot that runs inside the platform API."""

    # Run the trading loop on startup. Tests and one-off scripts turn it off.
    BOT_ENABLED: bool = True

    # Market data: "mock" (synthetic random walk, works offline, the default) or "yfinance"
    # (live Yahoo Finance quotes, delayed by seconds to minutes). Switchable at runtime from the
    # bot settings page.
    MARKET_DATA_PROVIDER: str = "mock"
    # Yahoo Finance is polled at most this often; between polls the last quotes are reused.
    YFINANCE_MIN_INTERVAL_SECONDS: float = 10.0

    # Execution: "exchange" sends every entry and exit as an IOC order to the platform's own
    # order book (in process, no HTTP); "simulated" fills locally with random slippage.
    EXECUTION_MODE: str = "exchange"
    # The bot's account on the exchange (created on startup, cannot sign in).
    BOT_EMAIL: str = "trading-engine@example.com"
    # How far past the quote an IOC order may fill.
    EXCHANGE_PRICE_TOLERANCE_BPS: float = 20.0

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = BotSettings()
