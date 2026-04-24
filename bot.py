import asyncio

from aiogram import Bot, Dispatcher

from bot.handlers import router
from bot.server import start_bot_server
from config import Config, logger


async def main():
    if not Config.BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN не задан!")
        return

    bot = Bot(token=Config.BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Запуск Telegram бота...")
    await start_bot_server(bot, dp)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Бот остановлен пользователем")
