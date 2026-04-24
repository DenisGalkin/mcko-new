import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.types import FSInputFile, InlineKeyboardButton
from aiohttp import web
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Config, logger
from shared.manager import load_data, merge_telegram_message_map


def build_notification_keyboard(task_number):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📝 Ответ", callback_data=f"task:answer:{task_number}"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="📎 Получить файл", callback_data=f"task:file:{task_number}"
        ),
        InlineKeyboardButton(
            text="🧾 Текст", callback_data=f"task:text:{task_number}"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="📂 Открыть карточку", callback_data=f"task:view:{task_number}"
        )
    )
    return builder.as_markup()


async def notify_subscribers(bot: Bot, task_number, filename, task_text=""):
    task_text = (task_text or "").strip()
    path = Config.UPLOAD_DIR / filename if filename else None
    count = 0
    message_map_updates = {}

    for chat_id in load_data().get("telegram_subscribers", {}):
        try:
            if path and path.exists():
                caption = [f"📑 Новое задание #{task_number}"]
                if task_text:
                    caption.append("К заданию прикреплен текст. Нажмите '🧾 Текст'.")
                caption.append(
                    "Ответьте на это сообщение текстом, чтобы сохранить ответ."
                )
                msg = await bot.send_document(
                    chat_id,
                    FSInputFile(path),
                    caption="\n\n".join(caption),
                    reply_markup=build_notification_keyboard(task_number),
                )
            else:
                body = [f"🧾 Новое текстовое задание #{task_number}"]
                if task_text:
                    body.append(task_text)
                body.append(
                    "Ответьте на это сообщение текстом, чтобы сохранить ответ."
                )
                msg = await bot.send_message(
                    chat_id,
                    "\n\n".join(body),
                    reply_markup=build_notification_keyboard(task_number),
                )
            message_map_updates[f"{chat_id}:{msg.message_id}"] = {
                "task_number": task_number,
                "at": datetime.now().isoformat(),
            }
            count += 1
        except Exception as e:
            logger.error(f"Ошибка рассылки пользователю {chat_id}: {e}")

    merge_telegram_message_map(message_map_updates)
    logger.info(f"Рассылка завершена. Уведомлено: {count} чел.")


async def start_bot_server(bot: Bot, dp: Dispatcher):
    app = web.Application()

    async def handle_webhook(request):
        try:
            payload = await request.json()
            logger.info(f"Получено уведомление от Web: {payload}")
            asyncio.create_task(
                notify_subscribers(
                    bot,
                    payload["task_number"],
                    payload.get("filename", ""),
                    payload.get("task_text", ""),
                )
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
