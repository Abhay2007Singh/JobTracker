# Configures application-wide logging with file rotation and console output.

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from app.config import config


def setup_logger(name: str) -> logging.Logger:
    log_dir = Path(config.LOG_DIR)
    log_dir.mkdir(exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%d/%m/%Y %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    # Rotate at 5 MB, keep 3 backups
    file_handler = RotatingFileHandler(
        log_dir / "jobtracker.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
