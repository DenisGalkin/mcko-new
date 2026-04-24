import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.types import FSInputFile
from aiohttp import web

from config import Config, logger
from shared.manager import load_data, save_data


async def notify_subscribers(bot: Bot, task_number, filename):
    data = load_data()
    path = Config.UPLOAD_DIR / filename
    count = 0

    for chat_id in data.get("telegram_subscribers", {}):
        try:
            msg = await bot.send_document(
                chat_id,
                FSInputFile(path),
                caption=f"📑 Новое задание #{task_number}\n\nОтветьте на это сообщение текстом, чтобы сохранить ответ.",
            )
            data["telegram_message_map"][f"{chat_id}:{msg.message_id}"] = {
                "task_number": task_number,
                "at": datetime.now().isoformat(),
            }
            count += 1
        except Exception as e:
            logger.error(f"Ошибка рассылки пользователю {chat_id}: {e}")

    save_data(data)
    logger.info(f"Рассылка завершена. Уведомлено: {count} чел.")


async def start_bot_server(bot: Bot, dp: Dispatcher):
    app = web.Application()

    async def handle_webhook(request):
        try:
            payload = await request.json()
            logger.info(f"Получено уведомление от Web: {payload}")
            asyncio.create_task(
                notify_subscribers(bot, payload["task_number"], payload["filename"])
            )
            return web.json_response({"ok": True})
        except Exception as e:
            logger.exception("Ошибка в обработчике уведомлений")
            return web.json_response({"ok": False}, status=500)

    app.router.add_post("/notify", handle_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", Config.BOT_PORT)

    logger.info(f"Внутренний сервер бота запущен на порту {Config.BOT_PORT}")
    await asyncio.gather(site.start(), dp.start_polling(bot))
