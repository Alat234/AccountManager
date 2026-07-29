import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ui.app import App


def setup_logging() -> None:
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        logs_dir / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console_handler)

if __name__ == "__main__":
    setup_logging()
    app = App()
    app.mainloop()
