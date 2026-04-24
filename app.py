from config import Config, logger
from web import create_app

app = create_app()

if __name__ == "__main__":
    logger.info(f"Запуск Web-сервиса на порту {Config.WEB_PORT}")
    app.run(host="0.0.0.0", port=Config.WEB_PORT)
