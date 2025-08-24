from __future__ import annotations

import logging
import os
import signal

from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from handlers.commands import start, newgame, board, send_invite_link, choose_mode
from handlers.router import router_text

BOARD15_ENABLED = os.getenv("BOARD15_ENABLED") == "1"
if BOARD15_ENABLED:
    from game_board15.handlers import board15, board15_on_click


token = os.getenv("BOT_TOKEN")
if not token:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

webhook_url = os.getenv("WEBHOOK_URL")
if not webhook_url:
    raise RuntimeError("WEBHOOK_URL environment variable is not set")
webhook_url = webhook_url.rstrip("/")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _handle_exit(sig: int, frame: object | None) -> None:
    """Log received termination signals for easier debugging on platforms like
    Render where processes may be stopped externally."""
    logger.info("Received shutdown signal %s", sig)


signal.signal(signal.SIGTERM, _handle_exit)
signal.signal(signal.SIGINT, _handle_exit)

# Disable the built-in Updater as we rely solely on webhooks for receiving
# updates.  Starting the default Updater would trigger long-polling which
# conflicts with webhook mode and may lead to the application shutting down
# shortly after startup on some platforms (e.g. Render) when the polling task
# fails.  By explicitly disabling it, the application runs purely in webhook
# mode.
bot_app = ApplicationBuilder().token(token).updater(None).build()
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("newgame", newgame))
bot_app.add_handler(CommandHandler("board", board))
bot_app.add_handler(CallbackQueryHandler(send_invite_link, pattern="^get_link$"))
bot_app.add_handler(CallbackQueryHandler(choose_mode, pattern="^mode_"))
if BOARD15_ENABLED:
    bot_app.add_handler(CommandHandler("board15", board15))
    bot_app.add_handler(CallbackQueryHandler(board15_on_click, pattern=r"^b15\|"))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router_text))


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling update %s", update, exc_info=context.error)


bot_app.add_error_handler(handle_error)


app = FastAPI()


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Starting bot application")
    try:
        await bot_app.initialize()
        await bot_app.start()
        webhook = f"{webhook_url}/webhook"
        await bot_app.bot.set_webhook(webhook)
        logger.info("Webhook set to %s", webhook)
    except Exception:
        logger.exception("Failed during startup")
        raise
    else:
        logger.info("Bot application started successfully")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("Shutting down bot application")
    try:
        await bot_app.bot.delete_webhook()
        await bot_app.stop()
        await bot_app.shutdown()
    except Exception:
        logger.exception("Error during shutdown")
        raise
    else:
        logger.info("Bot application stopped")


@app.post("/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    update = Update.de_json(await request.json(), bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}


@app.api_route("/", methods=["GET", "HEAD"])
async def root() -> dict[str, str]:
    return {"status": "running"}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Simple health-check endpoint for Render.

    Returns a JSON response indicating the application is up. Used by the
    hosting platform to verify the service is healthy.
    """
    return {"status": "ok"}
