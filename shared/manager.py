import json

from config import Config, logger


def load_data():
    if not Config.DATA_FILE.exists():
        return {"tasks": {}, "telegram_subscribers": {}, "telegram_message_map": {}}
    try:
        return json.loads(Config.DATA_FILE.read_text(encoding="utf-8"))
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


def get_task_file(task_num):
    prefix = f"{task_num}."
    for path in Config.UPLOAD_DIR.iterdir():
        if path.is_file() and path.name.startswith(prefix):
            return path
    return None


def cleanup_data():
    data = load_data()
    initial_count = len(data["tasks"])
    to_del = [
        k
        for k, v in data["tasks"].items()
        if not (Config.UPLOAD_DIR / v["filename"]).is_file()
    ]
    for k in to_del:
        data["tasks"].pop(k)
        logger.info(f"Очищена запись для задания #{k} (файл не найден)")

    if to_del:
        save_data(data)
    return data
