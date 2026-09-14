# server/task_manager.py
import asyncio
import uuid
import logging
from core import config
from cli import main as cli_main
from server.log_handler import make_ws_handler
from server.ws_bus import bus
import sys
from core.logger_config import setup_logging

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
        self.encoding = "utf-8"

    def write(self, s):
        for line in s.split('\n'):
            line = line.rstrip()
            if line:
                self.logger.info(line)

    def flush(self):
        pass

    def isatty(self):
        return False

    def fileno(self):
        raise OSError("_StdoutToLog has no fileno")

def _run_cli_in_thread(task_id: str, req):
    """在独立线程里运行 cli_main —— 同步代码在这里跑，不阻塞主事件循环"""

    setup_logging()

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
        if req.mode == 2 and not req.ids:
            raise ValueError("模式2需要至少一个 ID")
        if req.mode == 1 and not (req.episode_urls or (req.episode_template and req.episode_count)):
            raise ValueError("模式1需要提供 URL 列表或模板+集数")

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

_running_lock = asyncio.Lock()

async def _run_download(task_id: str, req):
    """异步入口：把同步任务丢到线程池"""
    if _running_lock.locked():
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = "已有任务在运行，暂不支持并发"
        await bus.publish(task_id, {"type": "status", "status": "failed",
                                    "error": "已有任务在运行，暂不支持并发"})
        return

    async with _running_lock:
        tasks[task_id]["status"] = "running"
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, _run_cli_in_thread, task_id, req)
        except Exception as e:
            # ✅ 兜底：任何逃出 _run_cli_in_thread 的异常都在这里被记下来
            logging.error(f"任务线程异常：{task_id}", exc_info=True)
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = str(e)
            await bus.publish(task_id, {"type": "status", "status": "failed", "error": str(e)})

    asyncio.create_task(_cleanup_later(task_id))    # ← 这行在 async with 外面

_background_tasks: set[asyncio.Task] = set()

async def _cleanup_later(task_id: str, delay: int = 300):
    """5 分钟后清理任务，避免内存累积"""
    await asyncio.sleep(delay)
    tasks.pop(task_id, None)
    await bus.clear_history(task_id)

def create_task(req) -> str:
    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {"status": "pending", "error": None}
    t = asyncio.create_task(_run_download(task_id, req))
    _background_tasks.add(t)
    t.add_done_callback(_background_tasks.discard)
    return task_id