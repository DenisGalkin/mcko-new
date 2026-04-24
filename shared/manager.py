import json

from config import Config, logger


def build_task_key(user_id, task_number):
    return f"{int(user_id)}:{int(task_number)}"


def parse_task_key(task_key):
    raw_user_id, raw_task_number = str(task_key).split(":", 1)
    return int(raw_user_id), int(raw_task_number)


def empty_data():
    return {
        "tasks": {},
        "users": {},
        "telegram_subscribers": {},
        "telegram_message_map": {},
        "next_user_id": 1,
    }


def load_data():
    if not Config.DATA_FILE.exists():
        return empty_data()
    try:
        data = json.loads(Config.DATA_FILE.read_text(encoding="utf-8"))
        data.setdefault("tasks", {})
        data.setdefault("users", {})
        data.setdefault("telegram_subscribers", {})
        data.setdefault("telegram_message_map", {})
        data.setdefault("next_user_id", 1)

        normalized_tasks = {}
        for raw_key, raw_task in data["tasks"].items():
            task = dict(raw_task)
            if ":" in str(raw_key):
                parsed_user_id, parsed_task_number = parse_task_key(raw_key)
            else:
                parsed_user_id = 0
                parsed_task_number = int(task.get("task_number", raw_key))

            task_number = int(task.get("task_number", parsed_task_number))
            user_id = int(task.get("user_id", parsed_user_id))
            task_key = build_task_key(user_id, task_number)

            task.setdefault("answer_text", "")
            task.setdefault("task_text", "")
            task.setdefault("filename", "")
            task.setdefault("created", "")
            task["user_id"] = user_id
            task["task_number"] = task_number
            task["task_key"] = task_key
            normalized_tasks[task_key] = task
            data["users"].setdefault(str(user_id), {"created_at": task.get("created", "")})

        data["tasks"] = normalized_tasks
        return data
    except Exception as e:
        logger.error(f"Ошибка чтения базы данных: {e}")
        return empty_data()


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


def get_task(data, user_id, task_number):
    return data.setdefault("tasks", {}).get(build_task_key(user_id, task_number))


def save_task_answer(task_key, text):
    data = load_data()
    tasks = data.setdefault("tasks", {})
    task = tasks.get(str(task_key))
    if not task:
        return False

    task["answer_text"] = text
    save_data(data)
    return True


def save_task_description(task_key, text):
    data = load_data()
    tasks = data.setdefault("tasks", {})
    task = tasks.get(str(task_key))
    if not task:
        return False

    task["task_text"] = text
    save_data(data)
    return True


def get_task_file(task_num, user_id=None):
    prefix = f"{task_num}_{user_id}." if user_id is not None else f"{task_num}."
    for path in Config.UPLOAD_DIR.iterdir():
        if path.is_file() and path.name.startswith(prefix):
            return path

    if user_id is not None:
        legacy_prefix = f"{task_num}."
        for path in Config.UPLOAD_DIR.iterdir():
            if path.is_file() and path.name.startswith(legacy_prefix):
                return path
    return None


def get_tasks_for_user(data, user_id):
    tasks = [
        task
        for task in data.get("tasks", {}).values()
        if int(task.get("user_id", 0)) == int(user_id)
    ]
    return sorted(tasks, key=lambda item: int(item["task_number"]))


def get_next_task_number_for_user(data, user_id):
    user_tasks = get_tasks_for_user(data, user_id)
    return max([int(task["task_number"]) for task in user_tasks] or [0]) + 1


def allocate_user_id():
    data = load_data()
    user_id = int(data.get("next_user_id", 1))
    data.setdefault("users", {})
    data["users"][str(user_id)] = {"created_at": ""}
    data["next_user_id"] = user_id + 1
    save_data(data)
    return user_id


def has_user(data, user_id):
    return str(int(user_id)) in data.get("users", {})


def cleanup_data():
    data = load_data()
    to_del = [
        k
        for k, v in data["tasks"].items()
        if v.get("filename") and not (Config.UPLOAD_DIR / v["filename"]).is_file()
    ]
    for k in to_del:
        data["tasks"].pop(k)
        logger.info(f"Очищена запись для задания {k} (файл не найден)")

    if to_del:
        save_data(data)
    return data
