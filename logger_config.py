# logger_config.py

import logging
import config

def setup_logging():
    logging.basicConfig(
        filename='log.txt',
        filemode='a',
        level=logging.DEBUG if config.DEBUG else logging.INFO,
        format='[%(asctime)s] %(levelname)s - %(message)s',
        encoding='utf-8'
    )

