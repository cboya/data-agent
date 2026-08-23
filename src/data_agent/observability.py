"""Application logging setup."""

import logging
from logging.config import dictConfig


def configure_logging(level: str = "INFO") -> None:
    """Configure concise structured-enough logs without sensitive payloads."""
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                }
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                }
            },
            "root": {"handlers": ["default"], "level": level},
        }
    )
    logging.captureWarnings(True)
