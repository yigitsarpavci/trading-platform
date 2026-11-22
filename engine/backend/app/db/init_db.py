from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.db import base  # noqa: F401  (imports every model so Base knows its tables)
from app.db.session import Base
from app.models.user import User, WatchlistItem

DEFAULT_USER_EMAIL = "demo@alphatrigger.ai"
# The engine only trades this universe (see V8_UNIVERSE in main.py); a fresh database starts with it.
DEFAULT_WATCHLIST = ("BTC-USD", "ETH-USD", "SOL-USD", "LINK-USD", "LTC-USD")


def init_db(engine: Engine) -> None:
    """Create all tables (no-op when they exist), the demo user (id 1) and, on an empty watchlist,
    the default trading universe."""
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        if session.query(User).filter(User.id == 1).first() is None:
            session.add(User(email=DEFAULT_USER_EMAIL))
            session.commit()
        if session.query(WatchlistItem).count() == 0:
            session.add_all(
                WatchlistItem(user_id=1, ticker=t, asset_type="Crypto", priority="High") for t in DEFAULT_WATCHLIST
            )
            session.commit()
    finally:
        session.close()
