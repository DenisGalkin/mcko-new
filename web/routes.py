from datetime import datetime, timedelta

import requests
from flask import Blueprint, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from config import Config, logger
from shared.manager import (
    cleanup_data,
    get_task_file,
    load_data,
    save_data,
    save_task_description,
)

main = Blueprint("main", __name__)
START_TIME = datetime.now()


@main.route("/")
def index():
    data = cleanup_data()
    finish_ts = int((START_TIME + timedelta(minutes=Config.TEST_DURATION)).timestamp())
    tasks = [
        data["tasks"][k] for k in sorted(data["tasks"].keys(), key=lambda x: int(x))
    ]
    answers_map = {k: v.get("answer_text", "") for k, v in data["tasks"].items()}
    task_texts_map = {k: v.get("task_text", "") for k, v in data["tasks"].items()}
    return render_template(
        "index.html",
        tasks=tasks,
        finish_ts=finish_ts,
        answers_map=answers_map,
        task_texts_map=task_texts_map,
    )


@main.route("/admin")
def admin():
    data = cleanup_data()
    tasks = [
        data["tasks"][k] for k in sorted(data["tasks"].keys(), key=lambda x: int(x))
    ]
    return render_template("admin.html", tasks=tasks)


@main.route("/upload", methods=["POST"])
def upload():
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
    start_task_num = (
        int(raw_num)
        if raw_num.isdigit()
        else (max([int(k) for k in data["tasks"]] or [0]) + 1)
    )

    uploaded_tasks = []

    for offset, file in enumerate(files):
        task_num = start_task_num + offset
        ext = file.filename.split(".")[-1] if "." in file.filename else "bin"
        filename = secure_filename(f"{task_num}.{ext}")

        old = get_task_file(task_num)
        if old:
            old.unlink()
            logger.info(f"Перезаписан файл для задания #{task_num}")

        file.save(Config.UPLOAD_DIR / filename)
        logger.success(f"Файл {filename} успешно сохранен")

        task_info = {
            "task_number": task_num,
            "filename": filename,
            "created": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "answer_text": data["tasks"].get(str(task_num), {}).get("answer_text", ""),
            "task_text": task_text or data["tasks"].get(str(task_num), {}).get("task_text", ""),
        }

        data["tasks"][str(task_num)] = task_info
        uploaded_tasks.append(task_info)

    save_data(data)

    for task_info in uploaded_tasks:
        try:
            resp = requests.post(
                Config.BOT_URL,
                json={
                    "task_number": task_info["task_number"],
                    "filename": task_info["filename"],
                    "task_text": task_info.get("task_text", ""),
                },
                timeout=2,
            )
            logger.info(
                f"Запрос к боту для задания #{task_info['task_number']}: {resp.status_code}"
            )
        except Exception as e:
            logger.error(
                f"Не удалось уведомить бота по заданию #{task_info['task_number']}: {e}"
            )

    return jsonify(
        {
            "ok": True,
            "task": uploaded_tasks[0],
            "tasks": uploaded_tasks,
        }
    )


@main.route("/send-task-text", methods=["POST"])
def send_task_text():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"ok": False, "error": "Пустой запрос"}), 400

    text = str(payload.get("text", "")).strip()
    raw_num = str(payload.get("task_number", "")).strip()

    if not text:
        return jsonify({"ok": False, "error": "Текст пустой"}), 400

    data = load_data()
    task_num = (
        int(raw_num)
        if raw_num.isdigit()
        else (max([int(k) for k in data["tasks"]] or [0]) + 1)
    )

    existing = data["tasks"].get(str(task_num), {})
    task_info = {
        "task_number": task_num,
        "filename": existing.get("filename", ""),
        "created": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "answer_text": existing.get("answer_text", ""),
        "task_text": text,
    }
    data["tasks"][str(task_num)] = task_info
    save_data(data)

    try:
        resp = requests.post(
            Config.BOT_URL,
            json={
                "task_number": task_info["task_number"],
                "filename": task_info["filename"],
                "task_text": task_info["task_text"],
            },
            timeout=2,
        )
        logger.info(f"Текстовое задание #{task_num} отправлено в бота: {resp.status_code}")
    except Exception as e:
        logger.error(f"Не удалось уведомить бота по текстовому заданию #{task_num}: {e}")

    return jsonify({"ok": True, "task": task_info})


@main.route("/api/tasks")
def api_tasks():
    data = cleanup_data()
    tasks = [
        data["tasks"][k] for k in sorted(data["tasks"].keys(), key=lambda x: int(x))
    ]
    return jsonify({"ok": True, "tasks": tasks})


@main.route("/api/tasks/<task>", methods=["PATCH"])
def update_task(task):
    if not task.isdigit():
        return jsonify({"ok": False, "error": "Некорректный номер задания"}), 400

    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"ok": False, "error": "Пустой запрос"}), 400

    data = load_data()
    task_info = data["tasks"].get(task)
    if not task_info:
        return jsonify({"ok": False, "error": "Задание не найдено"}), 404

    if "answer_text" in payload:
        task_info["answer_text"] = str(payload.get("answer_text", ""))
    if "task_text" in payload:
        task_info["task_text"] = str(payload.get("task_text", ""))

    save_data(data)
    logger.success(f"Обновлено задание #{task}")
    return jsonify({"ok": True, "task": task_info})


@main.route("/files/<path:filename>")
def download(filename):
    logger.debug(f"Запрос на скачивание: {filename}")
    return send_from_directory(Config.UPLOAD_DIR, filename)


@main.route("/save-task-text", methods=["POST"])
def save_task_text():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"ok": False, "error": "Пустой запрос"}), 400

    task_num = str(payload.get("task_number", ""))
    text = payload.get("text", "")

    if not task_num.isdigit():
        return jsonify({"ok": False, "error": "Некорректный номер задания"}), 400

    data = load_data()
    if task_num not in data["tasks"]:
        return jsonify({"ok": False, "error": "Задание не найдено"}), 404

    if not save_task_description(task_num, text):
        return jsonify({"ok": False, "error": "Задание не найдено"}), 404

    logger.success(f"Сохранено описание для задания #{task_num}: {text}")
    return jsonify({"ok": True, "text": text})


@main.route("/delete/<task>", methods=["POST"])
def delete_task(task):
    data = load_data()
    if task not in data["tasks"]:
        return jsonify({"ok": False, "error": "Задание не найдено"}), 404

    file_path = get_task_file(int(task))
    if file_path and file_path.exists():
        file_path.unlink()
        logger.info(f"Удален файл задания #{task}: {file_path.name}")

    data["tasks"].pop(task)
    save_data(data)

    logger.success(f"Задание #{task} удалено")
    return jsonify({"ok": True})


@main.route("/answers")
def get_answers():
    data = load_data()
    answers = {k: v.get("answer_text", "") for k, v in data["tasks"].items()}
    return jsonify(answers)


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
    data["telegram_message_map"] = {}
    save_data(data)
    logger.success("Все задания и ответы удалены")
    return jsonify({"ok": True})
