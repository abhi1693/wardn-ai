import logging
import sys

from pythonjsonlogger.json import JsonFormatter

from app.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level.upper())
