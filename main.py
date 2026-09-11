import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ui.app import App


def setup_logging() -> None:
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # WebDriver wire logs include full page HTML, input values and signed URLs.
    # Scenario diagnostics already record redacted, targeted events.
    logging.getLogger('selenium.webdriver.remote.remote_connection').setLevel(logging.WARNING)
    logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)
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
    logging.getLogger(__name__).info(
        "Runtime frozen=%s python=%s executable=%s cwd=%s rk_revision=20260909-multi-pdf",
        bool(getattr(sys, 'frozen', False)), sys.version.split()[0], sys.executable, Path.cwd(),
    )

if __name__ == "__main__":
    setup_logging()
    app = App()
    app.mainloop()
