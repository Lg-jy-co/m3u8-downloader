# server/task_manager.py
import asyncio
import uuid
import logging
from core import config
from cli import main as cli_main
from server.log_handler import make_ws_handler
from server.ws_bus import bus
import sys

tasks = {}
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop):
    """FastAPI 启动时把主事件循环注册进来"""
    global _main_loop
    _main_loop = loop

class _StdoutToLog:
    """把 print 的输出转成 logging.info，这样会同时进终端和 WebSocket"""
    def __init__(self, logger):
        self.logger = logger

    def write(self, s):
        s = s.rstrip()
        if s:
            self.logger.info(s)

    def flush(self):
        pass

def _run_cli_in_thread(task_id: str, req):
    """在独立线程里运行 cli_main —— 同步代码在这里跑，不阻塞主事件循环"""
    ws_handler = make_ws_handler(task_id, _main_loop)
    root_logger = logging.getLogger()
    root_logger.addHandler(ws_handler)

    # ← 加：把 print 重定向到 logging
    _old_stdout = sys.stdout
    sys.stdout = _StdoutToLog(logging.getLogger("stdout"))

    def _publish_status(status, **extra):
        if _main_loop is None or _main_loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(
            bus.publish(task_id, {"type": "status", "status": status, **extra}),
            _main_loop,
        )

    try:
        _publish_status("running")

        # 覆盖 config（注意：多个任务并行会互相干扰，暂时单任务可接受）
        config.RUN_MODE = req.mode
        if req.mode == 1:
            if req.series_name:
                config.SERIES_NAME = req.series_name
            if req.episode_urls:
                config.EPISODE_URLS = req.episode_urls
                config.EPISODE_URL_TEMPLATE = ""
                config.EPISODE_COUNT = 0
            elif req.episode_template and req.episode_count:
                config.EPISODE_URLS = []
                config.EPISODE_URL_TEMPLATE = req.episode_template
                config.EPISODE_COUNT = req.episode_count
                config.EPISODE_START = req.episode_start or 1
        elif req.mode == 2:
            if req.site_name:
                config.SITE_NAME = req.site_name
            if req.page_template:
                config.PAGE_URL_TEMPLATE = req.page_template
            if req.ids:
                config.ID_LIST = req.ids

        if req.output_dir:
            config.ROOT_SAVE_DIR = req.output_dir
        config.DEBUG = req.debug
        config.QUALITY_MODE = req.quality_mode
        config.AUTO_QUALITY_POLICY = req.auto_quality_policy

        # 关键：在子线程里新建一个事件循环跑 cli_main
        asyncio.run(cli_main())

        tasks[task_id]["status"] = "done"
        _publish_status("done")

    except Exception as e:
        logging.error(f"任务 {task_id} 失败", exc_info=True)
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = str(e)
        _publish_status("failed", error=str(e))
    finally:
        sys.stdout = _old_stdout  # ← 加：恢复
        root_logger.removeHandler(ws_handler)


async def _run_download(task_id: str, req):
    """异步入口：把同步任务丢到线程池"""
    tasks[task_id]["status"] = "running"
    loop = asyncio.get_running_loop()
    # run_in_executor 会把 _run_cli_in_thread 放到线程池里跑，主循环继续响应
    await loop.run_in_executor(None, _run_cli_in_thread, task_id, req)


def create_task(req) -> str:
    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {"status": "pending", "error": None}
    asyncio.create_task(_run_download(task_id, req))
    return task_id