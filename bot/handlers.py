from datetime import datetime

import requests
from aiogram import F, Router, types
from aiogram.filters import Command

from config import Config, logger
from shared.manager import load_data, save_data

router = Router()


@router.message(Command("start"))
async def start(m: types.Message):
    data = load_data()
    data["telegram_subscribers"][str(m.chat.id)] = {"date": datetime.now().isoformat()}
    save_data(data)
    logger.info(f"Новый подписчик: {m.chat.id}")

    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="/reset_timer")],
            [types.KeyboardButton(text="/delete_all")],
        ],
        resize_keyboard=True,
    )
    await m.answer(
        "✅ Подписка оформлена. Вы будете получать уведомления о новых файлах.",
        reply_markup=keyboard,
    )


@router.message(Command("reset_timer"))
async def reset_timer_cmd(m: types.Message):
    try:
        resp = requests.post(f"{Config.WEB_URL}/reset-timer", timeout=5)
        if resp.ok:
            await m.answer("⏱ Таймер сброшен.")
        else:
            await m.answer("❌ Не удалось сбросить таймер.")
    except Exception as e:
        logger.error(f"Ошибка сброса таймера: {e}")
        await m.answer("❌ Ошибка связи с сервером.")


@router.message(Command("delete_all"))
async def delete_all_cmd(m: types.Message):
    try:
        resp = requests.post(f"{Config.WEB_URL}/delete-all", timeout=5)
        if resp.ok:
            await m.answer("🗑 Все задания и ответы удалены.")
        else:
            await m.answer("❌ Не удалось удалить данные.")
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        await m.answer("❌ Ошибка связи с сервером.")


@router.message(F.reply_to_message)
async def handle_reply(m: types.Message):
    if not m.text or m.text.startswith("/"):
        return

    data = load_data()
    key = f"{m.chat.id}:{m.reply_to_message.message_id}"
    mapping = data["telegram_message_map"].get(key)

    if mapping:
        task_num = str(mapping["task_number"])
        data["tasks"][task_num]["answer_text"] = m.text
        save_data(data)
        logger.success(f"Сохранен ответ от {m.chat.id} для задания #{task_num}")
        await m.answer(f"💾 Ответ к #{task_num} сохранен")
