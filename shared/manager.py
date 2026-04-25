import sqlite3
import threading
import time
from contextlib import contextmanager

from config import Config, logger

TASK_SEQUENCE = [
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10.1",
    "10.2",
    "10.3",
]

SPECIAL_TASK_INPUTS = {
    "101": "10.1",
    "10.1": "10.1",
    "10,1": "10.1",
    "102": "10.2",
    "10.2": "10.2",
    "10,2": "10.2",
    "103": "10.3",
    "10.3": "10.3",
    "10,3": "10.3",
}

_DB_LOCK = threading.RLock()
_DB_READY = False
_LAST_CLEANUP_TS = 0.0


def normalize_task_number(raw_value):
    raw = str(raw_value or "").strip()
    if not raw:
        return None

    raw = raw.replace(",", ".")
    if raw in SPECIAL_TASK_INPUTS:
        return SPECIAL_TASK_INPUTS[raw]

    if raw.isdigit() and raw in TASK_SEQUENCE:
        return raw

    return raw if raw in TASK_SEQUENCE else None


def task_number_to_code(task_number):
    normalized = normalize_task_number(task_number)
    if not normalized:
        raise ValueError(f"Unsupported task number: {task_number}")
    return normalized.replace(".", "")


def task_code_to_number(task_code):
    raw = str(task_code or "").strip()
    if raw in {"101", "102", "103"}:
        return f"10.{raw[-1]}"
    return raw


def task_sort_key(task_number):
    normalized = normalize_task_number(task_number)
    if normalized in TASK_SEQUENCE:
        return TASK_SEQUENCE.index(normalized)
    return len(TASK_SEQUENCE)


def get_next_task_number(task_number, offset=1):
    normalized = normalize_task_number(task_number)
    if normalized not in TASK_SEQUENCE:
        return TASK_SEQUENCE[0]

    index = TASK_SEQUENCE.index(normalized) + int(offset)
    if index < 0:
        index = 0
    if index >= len(TASK_SEQUENCE):
        index = len(TASK_SEQUENCE) - 1
    return TASK_SEQUENCE[index]


def build_task_key(user_id, task_number):
    return f"{int(user_id)}:{task_number_to_code(task_number)}"


def parse_task_key(task_key):
    raw_user_id, raw_task_number = str(task_key).split(":", 1)
    return int(raw_user_id), task_code_to_number(raw_task_number)


def empty_data():
    return {
        "tasks": {},
        "users": {},
        "telegram_subscribers": {},
        "telegram_message_map": {},
        "next_user_id": 1,
    }


def _connect():
    conn = sqlite3.connect(
        Config.DB_FILE,
        timeout=Config.SQLITE_TIMEOUT,
        isolation_level=None,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def _transaction():
    init_db()
    with _DB_LOCK:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


def init_db():
    global _DB_READY
    if _DB_READY:
        return

    with _DB_LOCK:
        if _DB_READY:
            return

        Config.DB_FILE.parent.mkdir(exist_ok=True)
        conn = _connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    task_key TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    task_number TEXT NOT NULL,
                    task_code TEXT NOT NULL,
                    filename TEXT NOT NULL DEFAULT '',
                    created TEXT NOT NULL DEFAULT '',
                    answer_text TEXT NOT NULL DEFAULT '',
                    task_text TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_user_sort ON tasks(user_id, task_code);
                CREATE INDEX IF NOT EXISTS idx_tasks_user_number ON tasks(user_id, task_number);

                CREATE TABLE IF NOT EXISTS telegram_subscribers (
                    chat_id TEXT PRIMARY KEY,
                    date TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS telegram_message_map (
                    message_key TEXT PRIMARY KEY,
                    task_key TEXT NOT NULL DEFAULT '',
                    task_number TEXT NOT NULL DEFAULT '',
                    task_code TEXT NOT NULL DEFAULT '',
                    user_id INTEGER NOT NULL DEFAULT 0,
                    at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_message_task_key ON telegram_message_map(task_key);
                """
            )
            conn.execute(
                """
                INSERT INTO meta(key, value)
                VALUES('next_user_id', '1')
                ON CONFLICT(key) DO NOTHING
                """
            )
            _DB_READY = True
        finally:
            conn.close()


def _row_to_task(row):
    if row is None:
        return None
    return {
        "task_key": row["task_key"],
        "user_id": int(row["user_id"]),
        "task_number": row["task_number"],
        "task_code": row["task_code"],
        "filename": row["filename"] or "",
        "created": row["created"] or "",
        "answer_text": row["answer_text"] or "",
        "task_text": row["task_text"] or "",
    }


def get_next_user_id():
    init_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'next_user_id'"
        ).fetchone()
        return int(row["value"]) if row and str(row["value"]).isdigit() else 1
    finally:
        conn.close()


def has_user(data, user_id):
    return str(int(user_id)) in data.get("users", {})


def user_exists(user_id):
    init_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM users WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def ensure_user(user_id, created_at=""):
    try:
        with _transaction() as conn:
            conn.execute(
                """
                INSERT INTO users(user_id, created_at)
                VALUES(?, ?)
                ON CONFLICT(user_id) DO NOTHING
                """,
                (int(user_id), str(created_at or "")),
            )
    except Exception as exc:
        logger.error(f"Ошибка ensure_user({user_id}): {exc}")


def allocate_user_id():
    try:
        with _transaction() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'next_user_id'"
            ).fetchone()
            user_id = int(row["value"]) if row and str(row["value"]).isdigit() else 1
            conn.execute(
                """
                INSERT INTO users(user_id, created_at)
                VALUES(?, '')
                ON CONFLICT(user_id) DO NOTHING
                """,
                (user_id,),
            )
            conn.execute(
                """
                INSERT INTO meta(key, value)
                VALUES('next_user_id', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(user_id + 1),),
            )
            return user_id
    except Exception as exc:
        logger.error(f"Ошибка выдачи user_id: {exc}")
        return 1


def get_task_by_key(task_key):
    init_db()
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT task_key, user_id, task_number, task_code, filename, created, answer_text, task_text
            FROM tasks
            WHERE task_key = ?
            """,
            (str(task_key),),
        ).fetchone()
        return _row_to_task(row)
    finally:
        conn.close()


def get_task_by_user_number(user_id, task_number):
    return get_task_by_key(build_task_key(user_id, task_number))


def upsert_task(task_info):
    task = {
        "task_key": str(task_info["task_key"]),
        "user_id": int(task_info["user_id"]),
        "task_number": str(task_info["task_number"]),
        "task_code": str(task_info.get("task_code") or task_number_to_code(task_info["task_number"])),
        "filename": str(task_info.get("filename", "")),
        "created": str(task_info.get("created", "")),
        "answer_text": str(task_info.get("answer_text", "")),
        "task_text": str(task_info.get("task_text", "")),
    }
    try:
        with _transaction() as conn:
            conn.execute(
                """
                INSERT INTO users(user_id, created_at)
                VALUES(?, '')
                ON CONFLICT(user_id) DO NOTHING
                """,
                (task["user_id"],),
            )
            conn.execute(
                """
                INSERT INTO tasks(
                    task_key, user_id, task_number, task_code, filename, created, answer_text, task_text
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_key) DO UPDATE SET
                    user_id = excluded.user_id,
                    task_number = excluded.task_number,
                    task_code = excluded.task_code,
                    filename = excluded.filename,
                    created = excluded.created,
                    answer_text = excluded.answer_text,
                    task_text = excluded.task_text
                """,
                (
                    task["task_key"],
                    task["user_id"],
                    task["task_number"],
                    task["task_code"],
                    task["filename"],
                    task["created"],
                    task["answer_text"],
                    task["task_text"],
                ),
            )
        return task
    except Exception as exc:
        logger.error(f"Ошибка upsert_task({task['task_key']}): {exc}")
        return None


def update_task_fields(task_key, answer_text=None, task_text=None):
    updates = []
    params = []
    if answer_text is not None:
        updates.append("answer_text = ?")
        params.append(str(answer_text))
    if task_text is not None:
        updates.append("task_text = ?")
        params.append(str(task_text))
    if not updates:
        return get_task_by_key(task_key)

    params.append(str(task_key))
    try:
        with _transaction() as conn:
            cursor = conn.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE task_key = ?",
                params,
            )
            if cursor.rowcount <= 0:
                return None
        return get_task_by_key(task_key)
    except Exception as exc:
        logger.error(f"Ошибка update_task_fields({task_key}): {exc}")
        return None


def save_task_answer(task_key, text):
    return update_task_fields(task_key, answer_text=text) is not None


def save_task_description(task_key, text):
    return update_task_fields(task_key, task_text=text) is not None


def delete_task_record(task_key):
    try:
        with _transaction() as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE task_key = ?", (str(task_key),))
            return cursor.rowcount > 0
    except Exception as exc:
        logger.error(f"Ошибка delete_task_record({task_key}): {exc}")
        return False


def get_task_file(task_num, user_id=None, filename=None):
    if filename:
        path = Config.UPLOAD_DIR / filename
        if path.exists() and path.is_file():
            return path

    task_code = task_number_to_code(task_num)
    prefix = f"{task_code}_{user_id}." if user_id is not None else f"{task_code}."
    for path in Config.UPLOAD_DIR.iterdir():
        if path.is_file() and path.name.startswith(prefix):
            return path

    if user_id is not None:
        legacy_prefix = f"{task_code}."
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
    return sorted(tasks, key=lambda item: task_sort_key(item["task_number"]))


def get_tasks_for_user_db(user_id):
    init_db()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT task_key, user_id, task_number, task_code, filename, created, answer_text, task_text
            FROM tasks
            WHERE user_id = ?
            ORDER BY task_code
            """,
            (int(user_id),),
        ).fetchall()
        return sorted([_row_to_task(row) for row in rows], key=lambda item: task_sort_key(item["task_number"]))
    finally:
        conn.close()


def get_all_tasks():
    init_db()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT task_key, user_id, task_number, task_code, filename, created, answer_text, task_text
            FROM tasks
            """
        ).fetchall()
        tasks = [_row_to_task(row) for row in rows]
        return sorted(tasks, key=lambda item: (int(item["user_id"]), task_sort_key(item["task_number"])))
    finally:
        conn.close()


def get_next_task_number_for_user(data, user_id):
    user_tasks = get_tasks_for_user(data, user_id)
    if not user_tasks:
        return TASK_SEQUENCE[0]
    return get_next_task_number(user_tasks[-1]["task_number"])


def get_next_task_number_for_user_db(user_id):
    user_tasks = get_tasks_for_user_db(user_id)
    if not user_tasks:
        return TASK_SEQUENCE[0]
    return get_next_task_number(user_tasks[-1]["task_number"])


def get_answers_map_for_user(user_id):
    return {
        str(task["task_number"]): task.get("answer_text", "")
        for task in get_tasks_for_user_db(user_id)
    }


def set_subscriber(chat_id, date_value):
    try:
        with _transaction() as conn:
            conn.execute(
                """
                INSERT INTO telegram_subscribers(chat_id, date)
                VALUES(?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET date = excluded.date
                """,
                (str(chat_id), str(date_value or "")),
            )
        return True
    except Exception as exc:
        logger.error(f"Ошибка set_subscriber({chat_id}): {exc}")
        return False


def get_subscriber_chat_ids():
    init_db()
    conn = _connect()
    try:
        rows = conn.execute("SELECT chat_id FROM telegram_subscribers ORDER BY chat_id").fetchall()
        return [row["chat_id"] for row in rows]
    finally:
        conn.close()


def merge_telegram_message_map(entries):
    if not entries:
        return
    try:
        with _transaction() as conn:
            rows = []
            for message_key, payload in entries.items():
                rows.append(
                    (
                        str(message_key),
                        str(payload.get("task_key", "")),
                        str(payload.get("task_number", "")),
                        str(payload.get("task_code", "")),
                        int(payload.get("user_id", 0) or 0),
                        str(payload.get("at", "")),
                    )
                )
            conn.executemany(
                """
                INSERT INTO telegram_message_map(
                    message_key, task_key, task_number, task_code, user_id, at
                )
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_key) DO UPDATE SET
                    task_key = excluded.task_key,
                    task_number = excluded.task_number,
                    task_code = excluded.task_code,
                    user_id = excluded.user_id,
                    at = excluded.at
                """,
                rows,
            )
    except Exception as exc:
        logger.error(f"Ошибка обновления telegram_message_map: {exc}")


def get_message_mapping(message_key):
    init_db()
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT message_key, task_key, task_number, task_code, user_id, at
            FROM telegram_message_map
            WHERE message_key = ?
            """,
            (str(message_key),),
        ).fetchone()
        if row is None:
            return None
        return {
            "task_key": row["task_key"] or "",
            "task_number": row["task_number"] or "",
            "task_code": row["task_code"] or "",
            "user_id": int(row["user_id"] or 0),
            "at": row["at"] or "",
        }
    finally:
        conn.close()


def clear_all_data():
    try:
        with _transaction() as conn:
            conn.execute("DELETE FROM tasks")
            conn.execute("DELETE FROM users")
            conn.execute("DELETE FROM telegram_message_map")
            conn.execute("DELETE FROM telegram_subscribers")
            conn.execute(
                """
                INSERT INTO meta(key, value)
                VALUES('next_user_id', '1')
                ON CONFLICT(key) DO UPDATE SET value = '1'
                """
            )
        return True
    except Exception as exc:
        logger.error(f"Ошибка clear_all_data: {exc}")
        return False


def load_data(force=False):
    del force
    init_db()
    data = empty_data()
    data["next_user_id"] = get_next_user_id()

    for task in get_all_tasks():
        data["tasks"][task["task_key"]] = task

    conn = _connect()
    try:
        for row in conn.execute("SELECT user_id, created_at FROM users"):
            data["users"][str(int(row["user_id"]))] = {"created_at": row["created_at"] or ""}
        for row in conn.execute("SELECT chat_id, date FROM telegram_subscribers"):
            data["telegram_subscribers"][row["chat_id"]] = {"date": row["date"] or ""}
        for row in conn.execute(
            "SELECT message_key, task_key, task_number, task_code, user_id, at FROM telegram_message_map"
        ):
            data["telegram_message_map"][row["message_key"]] = {
                "task_key": row["task_key"] or "",
                "task_number": row["task_number"] or "",
                "task_code": row["task_code"] or "",
                "user_id": int(row["user_id"] or 0),
                "at": row["at"] or "",
            }
    finally:
        conn.close()
    return data


def cleanup_data(force=False):
    global _LAST_CLEANUP_TS
    now = time.monotonic()
    if not force and now - _LAST_CLEANUP_TS < Config.DATA_CLEANUP_INTERVAL:
        return load_data()

    try:
        with _transaction() as conn:
            rows = conn.execute("SELECT task_key, filename FROM tasks WHERE filename != ''").fetchall()
            to_delete = [
                row["task_key"]
                for row in rows
                if not (Config.UPLOAD_DIR / row["filename"]).is_file()
            ]
            for task_key in to_delete:
                conn.execute("DELETE FROM tasks WHERE task_key = ?", (task_key,))
                logger.info(f"Очищена запись для задания {task_key} (файл не найден)")
        _LAST_CLEANUP_TS = now
    except Exception as exc:
        logger.error(f"Ошибка cleanup SQLite: {exc}")

    return load_data()


init_db()
