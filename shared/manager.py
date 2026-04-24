import json

from config import Config, logger


def load_data():
    if not Config.DATA_FILE.exists():
        return {"tasks": {}, "telegram_subscribers": {}, "telegram_message_map": {}}
    try:
        data = json.loads(Config.DATA_FILE.read_text(encoding="utf-8"))
        data.setdefault("tasks", {})
        data.setdefault("telegram_subscribers", {})
        data.setdefault("telegram_message_map", {})
        for task in data["tasks"].values():
            task.setdefault("answer_text", "")
            task.setdefault("task_text", "")
            task.setdefault("filename", "")
        return data
    except Exception as e:
        logger.error(f"Ошибка чтения базы данных: {e}")
        return {"tasks": {}, "telegram_subscribers": {}, "telegram_message_map": {}}


def save_data(data):
    try:
        Config.DATA_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"Ошибка сохранения базы данных: {e}")


def merge_telegram_message_map(entries):
    if not entries:
        return

    data = load_data()
    data.setdefault("telegram_message_map", {})
    data["telegram_message_map"].update(entries)
    save_data(data)


def save_task_answer(task_num, text):
    data = load_data()
    tasks = data.setdefault("tasks", {})
    task = tasks.get(str(task_num))
    if not task:
        return False

    task["answer_text"] = text
    save_data(data)
    return True


def save_task_description(task_num, text):
    data = load_data()
    tasks = data.setdefault("tasks", {})
    task = tasks.get(str(task_num))
    if not task:
        return False

    task["task_text"] = text
    save_data(data)
    return True


def get_task_file(task_num):
    prefix = f"{task_num}."
    for path in Config.UPLOAD_DIR.iterdir():
        if path.is_file() and path.name.startswith(prefix):
            return path
    return None


def cleanup_data():
    data = load_data()
    to_del = [
        k
        for k, v in data["tasks"].items()
        if v.get("filename") and not (Config.UPLOAD_DIR / v["filename"]).is_file()
    ]
    for k in to_del:
        data["tasks"].pop(k)
        logger.info(f"Очищена запись для задания #{k} (файл не найден)")

    if to_del:
        save_data(data)
    return data
