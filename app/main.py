from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from handlers.commands import start, newgame, board
from handlers.router import router_text


token = os.getenv("BOT_TOKEN")
if not token:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

webhook_url = os.getenv("WEBHOOK_URL")
if not webhook_url:
    raise RuntimeError("WEBHOOK_URL environment variable is not set")
webhook_url = webhook_url.rstrip("/")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router_text))


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling update %s", update, exc_info=context.error)


bot_app.add_error_handler(handle_error)


app = FastAPI()


@app.on_event("startup")
async def on_startup() -> None:
    await bot_app.initialize()
    await bot_app.bot.set_webhook(f"{webhook_url}/webhook")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await bot_app.bot.delete_webhook()
    await bot_app.shutdown()


@app.post("/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    update = Update.de_json(await request.json(), bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}


@app.api_route("/", methods=["GET", "HEAD"])
async def root() -> dict[str, str]:
    return {"status": "running"}
