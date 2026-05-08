import logging
from logging.handlers import RotatingFileHandler

from core.constants import LOG_FILE


_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    try:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[
                RotatingFileHandler(
                    LOG_FILE,
                    maxBytes=2 * 1024 * 1024,
                    backupCount=5,
                    encoding='utf-8',
                ),
                logging.StreamHandler(),
            ],
        )
    except Exception:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[logging.StreamHandler()],
        )
    _CONFIGURED = True
