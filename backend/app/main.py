from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.api import api_router
from app.core.config import settings
from app.bot.api.router import api_router as bot_router
from app.bot.runner import start_bot
from app.db.init_db import init_db
from app.db.session import engine

app = FastAPI(
    title="Trading Platform API",
    description="Exchange (order book, settlement, market maker), personal finance and portfolio risk, "
    "and the trading bot that trades on the exchange.",
    version="2.0.0",
)

# CORS configuration
origins = ["http://localhost:3000"]
if hasattr(settings, "FRONTEND_CORS_ORIGINS") and settings.FRONTEND_CORS_ORIGINS:
    # E.g. FRONTEND_CORS_ORIGINS="http://localhost:3000,https://my-vercel-app.vercel.app"
    origins.extend([origin.strip() for origin in settings.FRONTEND_CORS_ORIGINS.split(",")])

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup() -> None:
    init_db(engine)  # every table, exchange and bot, from one metadata
    start_bot()      # the trading loop (one runner across workers; off when BOT_ENABLED=false)


app.include_router(api_router, prefix="/api/v1")
app.include_router(bot_router, prefix="/api/v1/bot")

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "message": "API is healthy and running!"}
