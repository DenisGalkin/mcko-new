import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)
logger.add("logs/app.log", rotation="10 MB", retention="7 days", level="DEBUG")


class Config:
    BASE_DIR = Path(__file__).resolve().parent
    UPLOAD_DIR = BASE_DIR / "uploads"
    DATA_FILE = BASE_DIR / "data.json"

    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    BOT_HOST = os.getenv("BOT_HOST", "localhost")
    WEB_HOST = os.getenv("WEB_HOST", "localhost")
    WEB_PORT = int(os.getenv("WEB_PORT", 1000))
    BOT_PORT = int(os.getenv("BOT_INTERNAL_PORT", 1001))
    BOT_URL = os.getenv("BOT_URL", f"http://{BOT_HOST}:{BOT_PORT}/notify")
    WEB_URL = os.getenv("WEB_URL", f"http://{WEB_HOST}:{WEB_PORT}")

    TEST_DURATION = 44


Config.UPLOAD_DIR.mkdir(exist_ok=True)
(Config.BASE_DIR / "logs").mkdir(exist_ok=True)
