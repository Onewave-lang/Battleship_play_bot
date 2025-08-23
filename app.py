from __future__ import annotations
import os
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from handlers.commands import start, newgame
from handlers.router import router_text


def main() -> None:
    token = os.getenv('BOT_TOKEN')
    if not token:
        raise RuntimeError('BOT_TOKEN environment variable is not set')
    application = ApplicationBuilder().token(token).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('newgame', newgame))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router_text))
    application.run_polling()


if __name__ == '__main__':
    main()
