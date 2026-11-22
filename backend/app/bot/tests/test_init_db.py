from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.models.user import BotAccount, WatchlistItem
from app.bot.seed import DEFAULT_USER_EMAIL, DEFAULT_WATCHLIST, init_db as seed_bot
from app.db.init_db import init_db


def memory_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    return engine


def test_one_database_holds_exchange_and_bot_tables_without_name_clashes():
    tables = set(inspect(memory_engine()).get_table_names())
    assert {"users", "orders", "trades", "assets"} <= tables  # exchange
    assert {"bot_accounts", "bot_signals", "bot_paper_trades", "bot_watchlist"} <= tables  # bot


def test_seed_creates_the_bot_account_and_default_universe():
    engine = memory_engine()
    seed_bot(engine)
    session = sessionmaker(bind=engine)()
    account = session.query(BotAccount).filter(BotAccount.id == 1).one()
    assert account.email == DEFAULT_USER_EMAIL and account.portfolio_value == 100000.0
    assert {w.ticker for w in session.query(WatchlistItem)} == set(DEFAULT_WATCHLIST)


def test_seed_is_idempotent_and_keeps_a_custom_watchlist():
    engine = memory_engine()
    seed_bot(engine)
    session = sessionmaker(bind=engine)()
    session.query(WatchlistItem).filter(WatchlistItem.ticker != "BTC-USD").delete()
    session.commit()
    seed_bot(engine)
    assert session.query(BotAccount).count() == 1
    assert [w.ticker for w in session.query(WatchlistItem)] == ["BTC-USD"]
