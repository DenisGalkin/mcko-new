from datetime import datetime, timedelta

import requests
from flask import Blueprint, jsonify, make_response, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from config import Config, logger
from shared.manager import (
    allocate_user_id,
    build_task_key,
    clear_all_data,
    cleanup_data,
    delete_task_record,
    ensure_user,
    get_all_tasks,
    get_answers_map_for_user,
    get_next_task_number,
    get_next_task_number_for_user_db,
    get_task_by_key,
    get_tasks_for_user_db,
    get_user_cookie_version,
    normalize_task_number,
    save_task_answer,
    update_task_fields,
    upsert_task,
    user_exists,
    task_number_to_code,
    task_sort_key,
)

main = Blueprint("main", __name__)
START_TIME = datetime.now()
USER_COOKIE_NAME = "mcko_user_id"
BOT_NOTIFY_SESSION = requests.Session()


def build_user_cookie_value(user_id, version=None):
    current_version = int(version or get_user_cookie_version())
    return f"{current_version}:{int(user_id)}"


def parse_user_cookie_value(raw_value):
    raw = str(raw_value or "").strip()
    if not raw:
        return None, None
    if ":" not in raw:
        return None, None
    raw_version, raw_user_id = raw.split(":", 1)
    if not raw_version.isdigit() or not raw_user_id.isdigit():
        return None, None
    return int(raw_version), int(raw_user_id)


def parse_task_number_tokens(raw_value):
    raw = str(raw_value or "").strip()
    if not raw:
        return []

    tokens = [token for token in raw.split() if token.strip()]
    normalized = []
    for token in tokens:
        task_number = normalize_task_number(token)
        if not task_number:
            raise ValueError(f"Некорректный номер задания: {token}")
        normalized.append(task_number)
    return normalized


def build_task_number_sequence(start_task_number, count):
    sequence = []
    current = normalize_task_number(start_task_number)
    if not current:
        current = get_next_task_number_for_user_db(0)

    for offset in range(int(count)):
        task_number = get_next_task_number(current, offset) if offset else current
        if sequence and task_number == sequence[-1]:
            raise ValueError("Недостаточно номеров заданий для загрузки всех файлов")
        sequence.append(task_number)
    return sequence


def get_current_user_id(create=False):
    cookie_version = get_user_cookie_version()
    raw_cookie_value = request.cookies.get(USER_COOKIE_NAME, "")
    parsed_version, parsed_user_id = parse_user_cookie_value(raw_cookie_value)
    if (
        parsed_version == cookie_version
        and parsed_user_id is not None
        and user_exists(parsed_user_id)
    ):
        return parsed_user_id, False
    if create:
        return allocate_user_id(), True
    return None, False


def with_user_cookie(response, user_id, created):
    if created:
        response.set_cookie(
            USER_COOKIE_NAME,
            build_user_cookie_value(user_id),
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
        resp = BOT_NOTIFY_SESSION.post(
            Config.BOT_URL,
            json={
                "task_key": task_info["task_key"],
                "task_number": task_info["task_number"],
                "user_id": task_info["user_id"],
                "filename": task_info["filename"],
                "task_text": task_info.get("task_text", ""),
            },
            timeout=Config.INTERNAL_HTTP_TIMEOUT,
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
    user_id, created = get_current_user_id(create=True)
    cleanup_data()
    finish_ts = int((START_TIME + timedelta(minutes=Config.TEST_DURATION)).timestamp())
    tasks = get_tasks_for_user_db(user_id)
    answers_map = get_answers_map_for_user(user_id)
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
    cleanup_data()
    tasks = sort_tasks_for_admin(get_all_tasks())
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

    raw_num = request.form.get("task_number", "").strip()
    task_text = request.form.get("task_text", "").strip()
    ensure_user(user_id, datetime.now().isoformat())

    try:
        requested_task_numbers = parse_task_number_tokens(raw_num)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if requested_task_numbers and len(requested_task_numbers) not in {1, len(files)}:
        return jsonify(
            {
                "ok": False,
                "error": "Количество номеров должно быть равно числу файлов или одному номеру",
            }
        ), 400

    start_task_num = requested_task_numbers[0] if requested_task_numbers else get_next_task_number_for_user_db(user_id)

    try:
        auto_task_numbers = (
            build_task_number_sequence(start_task_num, len(files))
            if len(requested_task_numbers) != len(files)
            else []
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    uploaded_tasks = []

    for offset, file in enumerate(files):
        if len(requested_task_numbers) == len(files):
            task_num = requested_task_numbers[offset]
        else:
            task_num = auto_task_numbers[offset]
        ext = file.filename.split(".")[-1] if "." in file.filename else "bin"
        task_key = build_task_key(user_id, task_num)
        filename = secure_filename(f"{task_number_to_code(task_num)}_{user_id}.{ext}")
        existing_task = get_task_by_key(task_key) or {}

        old_filename = existing_task.get("filename", "")
        old_path = Config.UPLOAD_DIR / old_filename if old_filename else None
        if old_path and old_path.exists() and old_path.is_file() and old_path.name != filename:
            old_path.unlink()
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
            "answer_text": existing_task.get("answer_text", ""),
            "task_text": task_text or existing_task.get("task_text", ""),
        }

        saved_task = upsert_task(task_info)
        if not saved_task:
            return jsonify({"ok": False, "error": "Не удалось сохранить задание"}), 500
        uploaded_tasks.append(saved_task)

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

    try:
        requested_task_numbers = parse_task_number_tokens(raw_num)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if len(requested_task_numbers) > 1:
        return jsonify({"ok": False, "error": "Для текста можно указать только один номер"}), 400

    task_num = requested_task_numbers[0] if requested_task_numbers else get_next_task_number_for_user_db(user_id)
    ensure_user(user_id, datetime.now().isoformat())

    task_key = build_task_key(user_id, task_num)
    existing = get_task_by_key(task_key) or {}
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
    saved_task = upsert_task(task_info)
    if not saved_task:
        return jsonify({"ok": False, "error": "Не удалось сохранить задание"}), 500

    notify_bot(saved_task)

    response = make_response(jsonify({"ok": True, "task": saved_task}))
    return with_user_cookie(response, user_id, created)


@main.route("/api/tasks")
def api_tasks():
    cleanup_data()
    tasks = sort_tasks_for_admin(get_all_tasks())
    return jsonify({"ok": True, "tasks": tasks})


@main.route("/api/tasks/<path:task_key>", methods=["PATCH", "DELETE"])
def update_task(task_key):
    payload = request.get_json(silent=True)
    if request.method == "PATCH" and not payload:
        return jsonify({"ok": False, "error": "Пустой запрос"}), 400

    task_info = get_task_by_key(task_key)
    if not task_info:
        return jsonify({"ok": False, "error": "Задание не найдено"}), 404

    if request.method == "DELETE":
        filename = task_info.get("filename", "")
        file_path = Config.UPLOAD_DIR / filename if filename else None
        if file_path and file_path.exists() and file_path.is_file():
            file_path.unlink()
        delete_task_record(task_key)
        logger.success(f"Удалено задание {task_key}")
        return jsonify({"ok": True})

    task_info = update_task_fields(
        task_key,
        answer_text=str(payload.get("answer_text", "")) if "answer_text" in payload else None,
        task_text=str(payload.get("task_text", "")) if "task_text" in payload else None,
    )
    if not task_info:
        return jsonify({"ok": False, "error": "Задание не найдено"}), 404
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

    task_key = build_task_key(user_id, task_num)
    if not get_task_by_key(task_key):
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
    task_key = build_task_key(user_id, task)
    task_info = get_task_by_key(task_key)
    if not task_info:
        return jsonify({"ok": False, "error": "Задание не найдено"}), 404

    filename = task_info.get("filename", "")
    file_path = Config.UPLOAD_DIR / filename if filename else None
    if file_path and file_path.exists():
        file_path.unlink()
        logger.info(f"Удален файл задания №{task} User {user_id}: {file_path.name}")

    delete_task_record(task_key)

    logger.success(f"Задание №{task} User {user_id} удалено")
    response = make_response(jsonify({"ok": True}))
    return with_user_cookie(response, user_id, created)


@main.route("/answers")
def get_answers():
    user_id, created = get_current_user_id(create=True)
    answers = get_answers_map_for_user(user_id)
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
    for task_info in get_all_tasks():
        filename = task_info.get("filename", "")
        if not filename:
            continue
        file_path = Config.UPLOAD_DIR / filename
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
            logger.info(f"Удален файл: {task_info['filename']}")
    clear_all_data()
    logger.success("Все задания, ответы и пользователи удалены")
    return jsonify({"ok": True})
