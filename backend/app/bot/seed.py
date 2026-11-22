from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.bot.config import settings
from app.bot.models.user import BotAccount, WatchlistItem

DEFAULT_USER_EMAIL = "demo@alphatrigger.ai"
# The bot only trades this universe (see V8_UNIVERSE in runner.py); a fresh database starts with it.
DEFAULT_WATCHLIST = ("BTC-USD", "ETH-USD", "SOL-USD", "LINK-USD", "LTC-USD")


def init_db(engine: Engine) -> None:
    """Make sure the bot account (id 1) exists and, on an empty watchlist, add the default
    universe. Tables are created by the platform's own init_db (one shared metadata)."""
    session = sessionmaker(bind=engine)()
    try:
        if session.query(BotAccount).filter(BotAccount.id == 1).first() is None:
            session.add(BotAccount(email=DEFAULT_USER_EMAIL))
            session.commit()
        if session.query(WatchlistItem).count() == 0:
            session.add_all(
                WatchlistItem(user_id=1, ticker=t, asset_type="Crypto", priority="High") for t in DEFAULT_WATCHLIST
            )
            session.commit()
    finally:
        session.close()


def ensure_exchange_account(session) -> int:
    """The bot's account on the exchange: holds its cash and coins. It has a random password,
    so nobody can sign in as the bot; returns its user id."""
    import secrets

    from app.core import security
    from app.models.all_models import User

    email = settings.BOT_EMAIL.lower()
    user = session.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, hashed_password=security.get_password_hash(secrets.token_urlsafe(32)))
        session.add(user)
        session.commit()
    return user.id
