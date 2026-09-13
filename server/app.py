# server/app.py
"""
FastAPI 应用入口
- 提供 /api/* 接口给前端调用
- 把 web/ 目录作为静态文件挂载，浏览器直接访问页面
"""

import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from server import task_manager
from server.schemas import TaskRequest
from fastapi import WebSocket, WebSocketDisconnect
from server.ws_bus import bus
import asyncio
from contextlib import asynccontextmanager


# 创建 FastAPI 实例
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时把主事件循环注册给 task_manager
    task_manager.set_main_loop(asyncio.get_running_loop())
    yield


app = FastAPI(title="M3U8 Downloader", version="2.0", lifespan=lifespan)

# ---------- API 路由 ----------
@app.get("/api/health")
def health():
    """健康检查：前端可用来探测后端是否活着"""
    return {"status": "ok", "service": "m3u8-downloader"}


@app.post("/api/tasks")
async def start_task(req: TaskRequest):
    """创建一个下载任务，立刻返回 task_id"""
    task_id = task_manager.create_task(req)
    return {"task_id": task_id, "status": "pending"}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    """查询任务状态"""
    if task_id not in task_manager.tasks:
        return {"error": "task not found"}
    return {"task_id": task_id, **task_manager.tasks[task_id]}


@app.websocket("/ws/tasks/{task_id}")
async def ws_task_logs(websocket: WebSocket, task_id: str):
    print(f"[WS] 收到 WebSocket 连接请求 task_id={task_id}")  # ← 加这一行
    await websocket.accept()
    await bus.subscribe(task_id, websocket)
    try:
        # 保持连接，等待客户端断开
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await bus.unsubscribe(task_id, websocket)


# ---------- 静态文件挂载 ----------
# 把 web/ 目录暴露为静态文件服务，访问 http://127.0.0.1:8000/ 时返回 web/index.html
# 注意：mount 必须放在所有 API 路由之后，否则 "/" 会拦截所有请求
_web_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
app.mount("/", StaticFiles(directory=_web_dir, html=True), name="web")