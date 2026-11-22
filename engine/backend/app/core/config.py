from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "AlphaTrigger AI"
    API_V1_STR: str = "/api/v1"
    
    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "user"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_DB: str = "alphatrigger"
    DATABASE_URL: Optional[str] = None

    # CORS: comma-separated list of allowed browser origins
    FRONTEND_CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Market Data
    MARKET_DATA_PROVIDER: str = "mock" # mock or yfinance

    # Execution: "simulated" fills locally with random slippage; "exchange" routes orders to the
    # Financial Analytics Dashboard's matching engine (see app/services/execution.py).
    EXECUTION_MODE: str = "simulated"
    EXCHANGE_URL: str = "http://localhost:8001"
    EXCHANGE_EMAIL: str = "trading-engine@example.com"
    EXCHANGE_PASSWORD: str = ""
    EXCHANGE_PRICE_TOLERANCE_BPS: float = 20.0  # how far past the quote an IOC order may fill

    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.FRONTEND_CORS_ORIGINS.split(",") if o.strip()]

    def get_database_url(self) -> str:
        url = self.DATABASE_URL or (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}/{self.POSTGRES_DB}"
        )
        # SQLAlchemy 2.1 maps a bare postgresql:// URL to psycopg 3; pin the installed psycopg2 driver.
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg2://" + url[len("postgresql://"):]
        return url

settings = Settings()
