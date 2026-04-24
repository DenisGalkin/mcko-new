from datetime import datetime, timedelta

import requests
from flask import Blueprint, jsonify, make_response, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from config import Config, logger
from shared.manager import (
    allocate_user_id,
    build_task_key,
    cleanup_data,
    get_task_file,
    get_next_task_number,
    get_tasks_for_user,
    get_next_task_number_for_user,
    has_user,
    load_data,
    normalize_task_number,
    save_data,
    save_task_answer,
    task_number_to_code,
    task_sort_key,
)

main = Blueprint("main", __name__)
START_TIME = datetime.now()
USER_COOKIE_NAME = "mcko_user_id"


def get_current_user_id(create=False):
    data = load_data()
    cookie_value = str(request.cookies.get(USER_COOKIE_NAME, "")).strip()
    if cookie_value.isdigit() and has_user(data, int(cookie_value)):
        return int(cookie_value), False
    if create:
        return allocate_user_id(), True
    return None, False


def with_user_cookie(response, user_id, created):
    if created:
        response.set_cookie(
            USER_COOKIE_NAME,
            str(user_id),
            max_age=60 * 60 * 24 * 365 * 5,
            samesite="Lax",
        )
    return response


def sort_tasks_for_admin(tasks):
    return sorted(
        tasks,
        key=lambda item: (int(item.get("user_id", 0)), task_sort_key(item.get("task_number"))),
    )


def notify_bot(task_info):
    try:
        resp = requests.post(
            Config.BOT_URL,
            json={
                "task_key": task_info["task_key"],
                "task_number": task_info["task_number"],
                "user_id": task_info["user_id"],
                "filename": task_info["filename"],
                "task_text": task_info.get("task_text", ""),
            },
            timeout=2,
        )
        logger.info(
            f"Запрос к боту для задания №{task_info['task_number']} "
            f"User {task_info['user_id']}: "
            f"{resp.status_code}"
        )
    except Exception as e:
        logger.error(
            f"Не удалось уведомить бота по заданию №{task_info['task_number']} "
            f"User {task_info['user_id']}: {e}"
        )


@main.route("/")
def index():
    data = cleanup_data()
    user_id, created = get_current_user_id(create=True)
    finish_ts = int((START_TIME + timedelta(minutes=Config.TEST_DURATION)).timestamp())
    tasks = get_tasks_for_user(data, user_id)
    answers_map = {str(task["task_number"]): task.get("answer_text", "") for task in tasks}
    task_texts_map = {str(task["task_number"]): task.get("task_text", "") for task in tasks}
    response = make_response(
        render_template(
        "index.html",
        tasks=tasks,
        finish_ts=finish_ts,
        answers_map=answers_map,
        task_texts_map=task_texts_map,
        current_user_id=user_id,
        )
    )
    return with_user_cookie(response, user_id, created)


@main.route("/admin")
def admin():
    data = cleanup_data()
    tasks = sort_tasks_for_admin(list(data["tasks"].values()))
    return render_template("admin.html", tasks=tasks)


@main.route("/upload", methods=["POST"])
def upload():
    user_id, created = get_current_user_id(create=True)
    files = request.files.getlist("files")
    if not files:
        single_file = request.files.get("file")
        if single_file:
            files = [single_file]

    files = [file for file in files if file and file.filename]
    if not files:
        logger.warning("Попытка загрузки без файла")
        return jsonify({"ok": False, "error": "Файлы не выбраны"}), 400

    data = load_data()
    raw_num = request.form.get("task_number", "").strip()
    task_text = request.form.get("task_text", "").strip()
    data.setdefault("users", {})
    data["users"].setdefault(str(user_id), {"created_at": datetime.now().isoformat()})
    start_task_num = normalize_task_number(raw_num) or get_next_task_number_for_user(
        data, user_id
    )

    uploaded_tasks = []

    for offset, file in enumerate(files):
        task_num = get_next_task_number(start_task_num, offset) if offset else start_task_num
        ext = file.filename.split(".")[-1] if "." in file.filename else "bin"
        task_key = build_task_key(user_id, task_num)
        filename = secure_filename(f"{task_number_to_code(task_num)}_{user_id}.{ext}")

        old = get_task_file(task_num, user_id)
        if old:
            old.unlink()
            logger.info(f"Перезаписан файл для задания №{task_num} User {user_id}")

        file.save(Config.UPLOAD_DIR / filename)
        logger.success(f"Файл {filename} успешно сохранен")

        task_info = {
            "task_key": task_key,
            "user_id": user_id,
            "task_number": task_num,
            "task_code": task_number_to_code(task_num),
            "filename": filename,
            "created": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "answer_text": data["tasks"].get(task_key, {}).get("answer_text", ""),
            "task_text": task_text or data["tasks"].get(task_key, {}).get("task_text", ""),
        }

        data["tasks"][task_key] = task_info
        uploaded_tasks.append(task_info)

    save_data(data)

    for task_info in uploaded_tasks:
        notify_bot(task_info)

    response = make_response(
        jsonify(
            {
            "ok": True,
            "task": uploaded_tasks[0],
            "tasks": uploaded_tasks,
            }
        )
    )
    return with_user_cookie(response, user_id, created)


@main.route("/send-task-text", methods=["POST"])
def send_task_text():
    user_id, created = get_current_user_id(create=True)
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"ok": False, "error": "Пустой запрос"}), 400

    text = str(payload.get("text", "")).strip()
    raw_num = str(payload.get("task_number", "")).strip()

    if not text:
        return jsonify({"ok": False, "error": "Текст пустой"}), 400

    data = load_data()
    task_num = normalize_task_number(raw_num) or get_next_task_number_for_user(data, user_id)
    data.setdefault("users", {})
    data["users"].setdefault(str(user_id), {"created_at": datetime.now().isoformat()})

    task_key = build_task_key(user_id, task_num)
    existing = data["tasks"].get(task_key, {})
    task_info = {
        "task_key": task_key,
        "user_id": user_id,
        "task_number": task_num,
        "task_code": task_number_to_code(task_num),
        "filename": existing.get("filename", ""),
        "created": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "answer_text": existing.get("answer_text", ""),
        "task_text": text,
    }
    data["tasks"][task_key] = task_info
    save_data(data)

    notify_bot(task_info)

    response = make_response(jsonify({"ok": True, "task": task_info}))
    return with_user_cookie(response, user_id, created)


@main.route("/api/tasks")
def api_tasks():
    data = cleanup_data()
    tasks = sort_tasks_for_admin(list(data["tasks"].values()))
    return jsonify({"ok": True, "tasks": tasks})


@main.route("/api/tasks/<path:task_key>", methods=["PATCH", "DELETE"])
def update_task(task_key):
    payload = request.get_json(silent=True)
    if request.method == "PATCH" and not payload:
        return jsonify({"ok": False, "error": "Пустой запрос"}), 400

    data = load_data()
    task_info = data["tasks"].get(task_key)
    if not task_info:
        return jsonify({"ok": False, "error": "Задание не найдено"}), 404

    if request.method == "DELETE":
        filename = task_info.get("filename", "")
        if filename:
            file_path = Config.UPLOAD_DIR / filename
            if file_path.exists() and file_path.is_file():
                file_path.unlink()
        data["tasks"].pop(task_key, None)
        save_data(data)
        logger.success(f"Удалено задание {task_key}")
        return jsonify({"ok": True})

    if "answer_text" in payload:
        task_info["answer_text"] = str(payload.get("answer_text", ""))
    if "task_text" in payload:
        task_info["task_text"] = str(payload.get("task_text", ""))

    save_data(data)
    logger.success(f"Обновлено задание {task_key}")
    return jsonify({"ok": True, "task": task_info})


@main.route("/files/<path:filename>")
def download(filename):
    logger.debug(f"Запрос на скачивание: {filename}")
    return send_from_directory(Config.UPLOAD_DIR, filename)


@main.route("/save-task-text", methods=["POST"])
def save_task_text():
    user_id, created = get_current_user_id(create=True)
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"ok": False, "error": "Пустой запрос"}), 400

    task_num = str(payload.get("task_number", ""))
    text = payload.get("text", "")

    task_num = normalize_task_number(task_num)
    if not task_num:
        return jsonify({"ok": False, "error": "Некорректный номер задания"}), 400

    data = load_data()
    task_key = build_task_key(user_id, task_num)
    if task_key not in data["tasks"]:
        return jsonify({"ok": False, "error": "Задание не найдено"}), 404

    if not save_task_answer(task_key, text):
        return jsonify({"ok": False, "error": "Задание не найдено"}), 404

    logger.success(f"Сохранен ответ для задания №{task_num} User {user_id}: {text}")
    response = make_response(jsonify({"ok": True, "text": text}))
    return with_user_cookie(response, user_id, created)


@main.route("/delete/<task>", methods=["POST"])
def delete_task(task):
    user_id, created = get_current_user_id(create=True)
    task = normalize_task_number(task)
    if not task:
        return jsonify({"ok": False, "error": "Некорректный номер задания"}), 400
    data = load_data()
    task_key = build_task_key(user_id, task)
    if task_key not in data["tasks"]:
        return jsonify({"ok": False, "error": "Задание не найдено"}), 404

    file_path = get_task_file(task, user_id)
    if file_path and file_path.exists():
        file_path.unlink()
        logger.info(f"Удален файл задания №{task} User {user_id}: {file_path.name}")

    data["tasks"].pop(task_key)
    save_data(data)

    logger.success(f"Задание №{task} User {user_id} удалено")
    response = make_response(jsonify({"ok": True}))
    return with_user_cookie(response, user_id, created)


@main.route("/answers")
def get_answers():
    data = load_data()
    user_id, created = get_current_user_id(create=True)
    answers = {
        str(task["task_number"]): task.get("answer_text", "")
        for task in get_tasks_for_user(data, user_id)
    }
    response = make_response(jsonify(answers))
    return with_user_cookie(response, user_id, created)


@main.route("/reset-timer", methods=["POST"])
def reset_timer():
    global START_TIME
    START_TIME = datetime.now()
    logger.success("Таймер сброшен")
    return jsonify({"ok": True})


@main.route("/delete-all", methods=["POST"])
def delete_all():
    data = load_data()
    for task_info in data.get("tasks", {}).values():
        filename = task_info.get("filename", "")
        if not filename:
            continue
        file_path = Config.UPLOAD_DIR / filename
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
            logger.info(f"Удален файл: {task_info['filename']}")
    data["tasks"] = {}
    data["users"] = {}
    data["telegram_message_map"] = {}
    data["next_user_id"] = 1
    save_data(data)
    logger.success("Все задания, ответы и пользователи удалены")
    return jsonify({"ok": True})
