from datetime import datetime

import requests
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Config, logger
from shared.manager import (
    build_task_key,
    get_task_file,
    load_data,
    merge_telegram_message_map,
    save_data,
    save_task_answer,
)

router = Router()
TASKS_PER_PAGE = 6
TELEGRAM_TEXT_LIMIT = 4000
TASKS_BUTTON_TEXT = "📚 Задания"
LATEST_BUTTON_TEXT = "🆕 Последнее"
HELP_BUTTON_TEXT = "ℹ️ Помощь"
RESET_BUTTON_TEXT = "⏱ Сбросить таймер"
DELETE_BUTTON_TEXT = "🗑 Очистить всё"
ALL_FILTER = "0"


def parse_task_ref(task_ref):
    raw_user_id, raw_task_number = str(task_ref).split("_", 1)
    return int(raw_user_id), raw_task_number


def encode_task_ref(task):
    return (
        f"{int(task['user_id'])}_"
        f"{task.get('task_code', str(task['task_number']).replace('.', ''))}"
    )


def task_label(task):
    return f"№{task['task_number']} User {int(task['user_id'])}"


def encode_list_state(page=0, user_id=ALL_FILTER, task_number=ALL_FILTER):
    return f"{int(page)}:{user_id}:{task_number}"


def parse_list_state(raw_state):
    parts = str(raw_state).split(":")
    page = int(parts[0]) if parts and parts[0] else 0
    user_id = parts[1] if len(parts) > 1 and parts[1] else ALL_FILTER
    task_number = parts[2] if len(parts) > 2 and parts[2] else ALL_FILTER
    return page, user_id, task_number


def task_state_badges(task):
    badges = []
    if task.get("filename"):
        badges.append("📎")
    if (task.get("task_text") or "").strip():
        badges.append("🧾")
    if (task.get("answer_text") or "").strip():
        badges.append("✅")
    return "".join(badges) or "•"


def parse_created_at(task):
    try:
        return datetime.strptime(task.get("created", ""), "%d.%m.%Y %H:%M:%S")
    except Exception:
        return datetime.min


def get_sorted_tasks(data):
    return sorted(
        data.get("tasks", {}).values(),
        key=lambda task: (
            parse_created_at(task),
            int(task.get("user_id", 0)),
            [int(part) for part in str(task.get("task_number", "999")).split(".")],
        ),
        reverse=True,
    )


def get_main_keyboard():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [
                types.KeyboardButton(text=TASKS_BUTTON_TEXT),
                types.KeyboardButton(text=LATEST_BUTTON_TEXT),
            ],
            [
                types.KeyboardButton(text=RESET_BUTTON_TEXT),
                types.KeyboardButton(text=DELETE_BUTTON_TEXT),
            ],
            [types.KeyboardButton(text=HELP_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
    )


def get_help_text():
    return (
        "Как читать задания в боте:\n"
        "• формат '№1 User 34' означает: задание 1 пользователя 34\n"
        "• одинаковые номера у разных пользователей больше не путаются\n\n"
        "Эмодзи в списке:\n"
        "• 📎 есть файл\n"
        "• 🧾 есть текст задания\n"
        "• ✅ есть сохраненный ответ\n\n"
        "Что умеет бот:\n"
        "• показывает все задания списком\n"
        "• умеет фильтровать список по User и по номеру задания\n"
        "• открывает карточку задания\n"
        "• заново присылает файл\n"
        "• показывает текст задания и сохраненный ответ\n\n"
        "Чтобы сохранить ответ:\n"
        "• ответьте текстом на сообщение с файлом или текстовым заданием"
    )


def get_filter_values(tasks):
    user_ids = sorted({str(int(task["user_id"])) for task in tasks}, key=int)
    task_numbers = sorted(
        {str(task["task_number"]) for task in tasks},
        key=lambda value: [int(part) for part in value.split(".")],
    )
    return user_ids, task_numbers


def filter_tasks(tasks, user_id=ALL_FILTER, task_number=ALL_FILTER):
    filtered = tasks
    if user_id != ALL_FILTER:
        filtered = [task for task in filtered if str(int(task["user_id"])) == str(user_id)]
    if task_number != ALL_FILTER:
        filtered = [task for task in filtered if str(task["task_number"]) == str(task_number)]
    return filtered


def get_filter_caption(user_id=ALL_FILTER, task_number=ALL_FILTER):
    user_label = f"User {user_id}" if user_id != ALL_FILTER else "все"
    task_label_text = f"№{task_number}" if task_number != ALL_FILTER else "все"
    return (
        "Эмодзи: 📎 файл, 🧾 текст, ✅ ответ.\n"
        f"Фильтры: {user_label} | "
        f"Задание {task_label_text}"
    )


def build_tasks_list_keyboard(all_tasks, tasks, page, user_id=ALL_FILTER, task_number=ALL_FILTER):
    builder = InlineKeyboardBuilder()
    start = page * TASKS_PER_PAGE
    page_tasks = tasks[start : start + TASKS_PER_PAGE]

    for task in page_tasks:
        builder.button(
            text=f"{task_label(task)} {task_state_badges(task)}",
            callback_data=(
                f"task:view:{encode_task_ref(task)}:"
                f"{encode_list_state(page, user_id, task_number)}"
            ),
        )

    if page_tasks:
        builder.adjust(1)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            types.InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"task:list:{encode_list_state(page - 1, user_id, task_number)}",
            )
        )
    if start + TASKS_PER_PAGE < len(tasks):
        nav_buttons.append(
            types.InlineKeyboardButton(
                text="Вперед ▶️",
                callback_data=f"task:list:{encode_list_state(page + 1, user_id, task_number)}",
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    user_ids, task_numbers = get_filter_values(all_tasks)
    current_user_pos = user_ids.index(str(user_id)) if user_id in user_ids else -1
    current_task_pos = (
        task_numbers.index(str(task_number)) if task_number in task_numbers else -1
    )

    prev_user = (
        user_ids[current_user_pos - 1]
        if current_user_pos > 0
        else ALL_FILTER if user_id != ALL_FILTER else None
    )
    next_user = (
        user_ids[current_user_pos + 1]
        if current_user_pos != -1 and current_user_pos < len(user_ids) - 1
        else user_ids[0] if user_id == ALL_FILTER and user_ids else None
    )
    prev_task = (
        task_numbers[current_task_pos - 1]
        if current_task_pos > 0
        else ALL_FILTER if task_number != ALL_FILTER else None
    )
    next_task = (
        task_numbers[current_task_pos + 1]
        if current_task_pos != -1 and current_task_pos < len(task_numbers) - 1
        else task_numbers[0] if task_number == ALL_FILTER and task_numbers else None
    )

    filter_row_user = []
    if prev_user is not None:
        filter_row_user.append(
            types.InlineKeyboardButton(
                text="◀️ User",
                callback_data=f"task:list:{encode_list_state(0, prev_user, task_number)}",
            )
        )
    filter_row_user.append(
        types.InlineKeyboardButton(
            text=f"User {user_id}" if user_id != ALL_FILTER else "User: все",
            callback_data=f"task:list:{encode_list_state(0, ALL_FILTER, task_number)}",
        )
    )
    if next_user is not None:
        filter_row_user.append(
            types.InlineKeyboardButton(
                text="User ▶️",
                callback_data=f"task:list:{encode_list_state(0, next_user, task_number)}",
            )
        )
    builder.row(*filter_row_user)

    filter_row_task = []
    if prev_task is not None:
        filter_row_task.append(
            types.InlineKeyboardButton(
                text="◀️ №",
                callback_data=f"task:list:{encode_list_state(0, user_id, prev_task)}",
            )
        )
    filter_row_task.append(
        types.InlineKeyboardButton(
            text=f"№{task_number}" if task_number != ALL_FILTER else "№: все",
            callback_data=f"task:list:{encode_list_state(0, user_id, ALL_FILTER)}",
        )
    )
    if next_task is not None:
        filter_row_task.append(
            types.InlineKeyboardButton(
                text="№ ▶️",
                callback_data=f"task:list:{encode_list_state(0, user_id, next_task)}",
            )
        )
    builder.row(*filter_row_task)

    if tasks:
        builder.row(
            types.InlineKeyboardButton(
                text=f"🆕 {task_label(tasks[0])}",
                callback_data=(
                    f"task:view:{encode_task_ref(tasks[0])}:"
                    f"{encode_list_state(page, user_id, task_number)}"
                ),
            )
        )

    return builder.as_markup()


def build_task_actions_keyboard(tasks, current_task, page=0, user_id=ALL_FILTER, task_number=ALL_FILTER):
    builder = InlineKeyboardBuilder()
    index = next(
        i for i, task in enumerate(tasks) if task["task_key"] == current_task["task_key"]
    )
    task_ref = encode_task_ref(current_task)

    builder.row(
        types.InlineKeyboardButton(
            text="📝 Показать ответ", callback_data=f"task:answer:{task_ref}"
        ),
        types.InlineKeyboardButton(
            text="🧾 Показать текст", callback_data=f"task:text:{task_ref}"
        ),
    )
    builder.row(
        types.InlineKeyboardButton(
            text="📎 Получить файл", callback_data=f"task:file:{task_ref}"
        )
    )

    nav_buttons = []
    if index > 0:
        nav_buttons.append(
            types.InlineKeyboardButton(
                text="◀️ Новее",
                callback_data=(
                    f"task:view:{encode_task_ref(tasks[index - 1])}:"
                    f"{encode_list_state(page, user_id, task_number)}"
                ),
            )
        )
    if index < len(tasks) - 1:
        nav_buttons.append(
            types.InlineKeyboardButton(
                text="Старее ▶️",
                callback_data=(
                    f"task:view:{encode_task_ref(tasks[index + 1])}:"
                    f"{encode_list_state(page, user_id, task_number)}"
                ),
            )
        )
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        types.InlineKeyboardButton(
            text="📚 К списку",
            callback_data=(
                f"task:list:{encode_list_state(index // TASKS_PER_PAGE, user_id, task_number)}"
            ),
        )
    )
    return builder.as_markup()


async def respond_or_edit(target_message, text, reply_markup=None, edit=False):
    if len(text) > TELEGRAM_TEXT_LIMIT:
        if edit:
            await send_text_chunks(target_message, text, reply_markup=reply_markup)
            return
        await send_text_chunks(target_message, text, reply_markup=reply_markup)
        return

    if edit:
        try:
            await target_message.edit_text(text, reply_markup=reply_markup)
            return
        except Exception:
            pass
    await target_message.answer(text, reply_markup=reply_markup)


def split_text_chunks(text, limit=TELEGRAM_TEXT_LIMIT):
    text = str(text or "")
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit // 2:
            split_at = limit

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    return [chunk for chunk in chunks if chunk] or [""]


async def send_text_chunks(target_message, text, reply_markup=None):
    chunks = split_text_chunks(text)
    for index, chunk in enumerate(chunks):
        await target_message.answer(
            chunk,
            reply_markup=reply_markup if index == len(chunks) - 1 else None,
        )


def format_task_card(task):
    answer_preview = (task.get("answer_text") or "").strip() or "Пока не сохранен"
    if len(answer_preview) > 300:
        answer_preview = f"{answer_preview[:300].rstrip()}..."

    file_label = task.get("filename") or "Без файла"
    has_text = "есть" if (task.get("task_text") or "").strip() else "нет"
    return (
        f"{task_label(task)}\n"
        f"Файл: {file_label}\n"
        f"Текст задания: {has_text}\n"
        f"Создано: {task.get('created', 'неизвестно')}\n\n"
        f"Ответ:\n{answer_preview}\n\n"
        "Откройте текст, файл или ответ кнопками ниже."
    )


async def send_tasks_list(target_message, page=0, edit=False, user_id=ALL_FILTER, task_number=ALL_FILTER):
    all_tasks = get_sorted_tasks(load_data())
    if not all_tasks:
        await respond_or_edit(target_message, "Заданий пока нет.", edit=edit)
        return

    tasks = filter_tasks(all_tasks, user_id=user_id, task_number=task_number)
    if not tasks:
        await respond_or_edit(
            target_message,
            "По выбранным фильтрам заданий нет.\n\n"
            "Эмодзи: 📎 файл, 🧾 текст, ✅ ответ.",
            reply_markup=build_tasks_list_keyboard(
                all_tasks, tasks, 0, user_id=user_id, task_number=task_number
            ),
            edit=edit,
        )
        return

    max_page = max((len(tasks) - 1) // TASKS_PER_PAGE, 0)
    page = max(0, min(page, max_page))
    start = page * TASKS_PER_PAGE + 1
    end = min((page + 1) * TASKS_PER_PAGE, len(tasks))
    text = (
        f"Задания: {start}-{end} из {len(tasks)}.\n"
        f"{get_filter_caption(user_id=user_id, task_number=task_number)}"
    )
    await respond_or_edit(
        target_message,
        text,
        reply_markup=build_tasks_list_keyboard(
            all_tasks, tasks, page, user_id=user_id, task_number=task_number
        ),
        edit=edit,
    )


async def send_task_card(
    target_message,
    user_id,
    task_number,
    edit=False,
    page=0,
    filter_user_id=ALL_FILTER,
    filter_task_number=ALL_FILTER,
):
    data = load_data()
    task = data.get("tasks", {}).get(build_task_key(user_id, task_number))
    tasks = filter_tasks(
        get_sorted_tasks(data),
        user_id=filter_user_id,
        task_number=filter_task_number,
    )
    if not tasks and task:
        tasks = [task]

    if not task:
        await respond_or_edit(
            target_message,
            f"❌ Не найдено задание №{task_number} User {user_id}",
            edit=edit,
        )
        return

    await respond_or_edit(
        target_message,
        format_task_card(task),
        reply_markup=build_task_actions_keyboard(
            tasks,
            task,
            page=page,
            user_id=filter_user_id,
            task_number=filter_task_number,
        ),
        edit=edit,
    )


async def resend_task_file(target_message, user_id, task_number):
    data = load_data()
    task = data.get("tasks", {}).get(build_task_key(user_id, task_number))
    file_path = get_task_file(task_number, user_id)

    if not task:
        await target_message.answer(f"❌ Не найдено задание №{task_number} User {user_id}")
        return

    if not file_path or not file_path.exists():
        await target_message.answer(f"❌ У задания {task_label(task)} нет файла")
        return

    msg = await target_message.answer_document(
        FSInputFile(file_path),
        caption=(
            f"📑 {task_label(task)}\n\n"
            "Ответьте на это сообщение текстом, чтобы сохранить или обновить ответ."
        ),
        reply_markup=build_task_actions_keyboard(get_sorted_tasks(data), task),
    )
    merge_telegram_message_map(
        {
            f"{target_message.chat.id}:{msg.message_id}": {
                "task_key": task["task_key"],
                "task_number": task_number,
                "task_code": task.get("task_code", str(task_number).replace(".", "")),
                "user_id": user_id,
                "at": datetime.now().isoformat(),
            }
        }
    )


async def send_task_answer(target_message, user_id, task_number):
    task = load_data().get("tasks", {}).get(build_task_key(user_id, task_number))
    if not task:
        await target_message.answer(f"❌ Не найдено задание №{task_number} User {user_id}")
        return

    answer = (task.get("answer_text") or "").strip()
    if answer:
        await send_text_chunks(
            target_message,
            f"📝 Ответ для {task_label(task)}:\n\n{answer}",
        )
    else:
        await target_message.answer(f"📝 Для {task_label(task)} ответ пока не сохранен")


async def send_task_text(target_message, user_id, task_number):
    task = load_data().get("tasks", {}).get(build_task_key(user_id, task_number))
    if not task:
        await target_message.answer(f"❌ Не найдено задание №{task_number} User {user_id}")
        return

    task_text = (task.get("task_text") or "").strip()
    if task_text:
        await send_text_chunks(
            target_message,
            f"🧾 Текст для {task_label(task)}:\n\n{task_text}",
        )
    else:
        await target_message.answer(f"🧾 У {task_label(task)} нет текста")


@router.message(Command("start"))
async def start(m: types.Message):
    data = load_data()
    data["telegram_subscribers"][str(m.chat.id)] = {"date": datetime.now().isoformat()}
    save_data(data)
    logger.info(f"Новый подписчик: {m.chat.id}")

    await m.answer(
        "✅ Подписка оформлена.\n\n"
        "Теперь бот показывает задания в формате '№1 User 34', "
        "и одинаковые номера у разных пользователей не путаются.",
        reply_markup=get_main_keyboard(),
    )
    await m.answer(get_help_text())


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


@router.message(Command("tasks"))
@router.message(F.text == TASKS_BUTTON_TEXT)
async def tasks_cmd(m: types.Message):
    await send_tasks_list(m)


@router.message(Command("latest"))
@router.message(F.text == LATEST_BUTTON_TEXT)
async def latest_cmd(m: types.Message):
    tasks = get_sorted_tasks(load_data())
    if not tasks:
        await m.answer("Заданий пока нет.")
        return
    task = tasks[0]
    await send_task_card(m, task["user_id"], task["task_number"])


@router.message(Command("help"))
@router.message(F.text == HELP_BUTTON_TEXT)
async def help_cmd(m: types.Message):
    await m.answer(get_help_text(), reply_markup=get_main_keyboard())


@router.message(F.text == RESET_BUTTON_TEXT)
async def reset_timer_button(m: types.Message):
    await reset_timer_cmd(m)


@router.message(F.text == DELETE_BUTTON_TEXT)
async def delete_all_button(m: types.Message):
    await delete_all_cmd(m)


@router.message(F.reply_to_message)
async def handle_reply(m: types.Message):
    if not m.text or m.text.startswith("/"):
        return

    data = load_data()
    key = f"{m.chat.id}:{m.reply_to_message.message_id}"
    mapping = data["telegram_message_map"].get(key)

    if mapping:
        task_key = mapping.get(
            "task_key",
            build_task_key(mapping.get("user_id", 0), mapping.get("task_number", "")),
        )
        if save_task_answer(task_key, m.text):
            user_id, task_number = mapping.get("user_id"), mapping.get("task_number")
            logger.success(
                f"Сохранен ответ от {m.chat.id} для задания №{task_number} User {user_id}"
            )
            await m.answer(f"💾 Ответ сохранен для №{task_number} User {user_id}")
        else:
            logger.warning(f"Не найдено задание для ответа от {m.chat.id}: {task_key}")
            await m.answer("❌ Задание для этого ответа не найдено")
        return

    logger.warning(
        f"Игнорирован reply без mapping: chat_id={m.chat.id}, "
        f"reply_message_id={m.reply_to_message.message_id}"
    )
    await m.answer("❌ Не нашел, к какому заданию относится этот reply")


@router.callback_query(F.data.startswith("task:list:"))
async def task_list_callback(callback: types.CallbackQuery):
    page, user_id, task_number = parse_list_state(callback.data.split("task:list:", 1)[1])
    await send_tasks_list(
        callback.message,
        page=page,
        edit=True,
        user_id=user_id,
        task_number=task_number,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("task:view:"))
async def task_view_callback(callback: types.CallbackQuery):
    payload = callback.data.split("task:view:", 1)[1]
    task_ref, raw_state = payload.split(":", 1)
    user_id, task_number = parse_task_ref(task_ref)
    page, filter_user_id, filter_task_number = parse_list_state(raw_state)
    await send_task_card(
        callback.message,
        user_id,
        task_number,
        edit=True,
        page=page,
        filter_user_id=filter_user_id,
        filter_task_number=filter_task_number,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("task:file:"))
async def task_file_callback(callback: types.CallbackQuery):
    user_id, task_number = parse_task_ref(callback.data.split("task:file:", 1)[1])
    await resend_task_file(callback.message, user_id, task_number)
    await callback.answer("Файл отправлен")


@router.callback_query(F.data.startswith("task:answer:"))
async def task_answer_callback(callback: types.CallbackQuery):
    user_id, task_number = parse_task_ref(callback.data.split("task:answer:", 1)[1])
    await send_task_answer(callback.message, user_id, task_number)
    await callback.answer()


@router.callback_query(F.data.startswith("task:text:"))
async def task_text_callback(callback: types.CallbackQuery):
    user_id, task_number = parse_task_ref(callback.data.split("task:text:", 1)[1])
    await send_task_text(callback.message, user_id, task_number)
    await callback.answer()


@router.message(F.text)
async def fallback_text(m: types.Message):
    if m.text.startswith("/"):
        return

    await m.answer(
        "Используйте '📚 Задания' для списка или 'ℹ️ Помощь' для подсказки.",
        reply_markup=get_main_keyboard(),
    )
