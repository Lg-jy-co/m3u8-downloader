# logger_config.py

import logging
from core import config


def setup_logging():
    root = logging.getLogger()
    # 只在第一次配置 handler
    if not any(isinstance(h, logging.FileHandler) for h in root.handlers):
        handler = logging.FileHandler('log.txt', mode='a', encoding='utf-8')
        handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s'))
        root.addHandler(handler)
    # 每次动态调整级别
    root.setLevel(logging.DEBUG if config.DEBUG else logging.INFO)

