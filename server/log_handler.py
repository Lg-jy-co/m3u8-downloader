# server/log_handler.py
import asyncio
import logging
from server.ws_bus import bus


class WebSocketLogHandler(logging.Handler):
    def __init__(self, task_id: str, main_loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.task_id = task_id
        self.main_loop = main_loop

    def emit(self, record):
        if self.main_loop is None or self.main_loop.is_closed():
            return
        try:
            msg = self.format(record)
            asyncio.run_coroutine_threadsafe(
                bus.publish(self.task_id, {
                    "type": "log",
                    "level": record.levelname,
                    "message": msg,
                }),
                self.main_loop,
            )
        except Exception:
            pass


def make_ws_handler(task_id: str, main_loop) -> WebSocketLogHandler:
    h = WebSocketLogHandler(task_id, main_loop)
    h.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s'))
    return h