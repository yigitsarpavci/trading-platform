from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.models import all_models  # noqa: F401  (registers every exchange table on Base)
from app.bot import models as bot_models  # noqa: F401  (and every bot table)
from app.models.all_models import Base

# Columns added after the initial schema. `create_all` only creates missing tables, so databases
# created before these columns existed get them here (Alembic revision 3c1e5a9b7d20 does the same).
_ADDED_COLUMNS = {
    "users": {"cash_balance": "FLOAT NOT NULL DEFAULT 100000"},
    "assets": {"reference_price": "FLOAT", "reference_price_at": "{timestamp}"},
    "orders": {"time_in_force": "VARCHAR(3) NOT NULL DEFAULT 'GTC'"},
}


def _add_missing_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    timestamp = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "TIMESTAMP"
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl.format(timestamp=timestamp)}"))


def init_db(engine: Engine) -> None:
    """Create missing tables and columns so a fresh or older database works without a manual migration."""
    Base.metadata.create_all(bind=engine)
    _add_missing_columns(engine)
