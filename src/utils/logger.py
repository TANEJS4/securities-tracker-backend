import logging
import os
import coloredlogs

from src.config.settings import settings


class Logger:
    def __init__(self, name: str = "app"):
        level = settings.LOG_LEVEL.upper()

        self.logger = logging.getLogger(name)

        log_format = (
            "%(asctime)s [%(levelname)s]  %(filename)s::%(funcName)s : %(message)s"
        )

        coloredlogs.install(
            level=level, logger=self.logger, fmt=log_format, datefmt="%Y-%m-%d %H:%M:%S"
        )

    def get_logger(self):
        return self.logger


logger = Logger().get_logger()
